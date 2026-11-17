"""Deterministic, currency-partitioned spend forecasting.

The engine is deliberately small and explainable:

* daily spend is read from de-duplicated billing rows, with missing days as zero;
* two transparent baselines are supported: seasonal naive (same weekday last
  week) and a flat moving average;
* every model is evaluated on a held-out tail using only information available
  before that tail;
* prediction intervals come from the empirical distribution of absolute holdout
  residuals, not from an assumed statistical distribution.

No AI, no cloud API and no floating point. Every value is ``Decimal``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ConfidenceLevel, ForecastGranularity, ForecastMethod
from app.core.errors import AppError
from app.core.time import utcnow
from app.db.models import CostRecord, ForecastPoint, ForecastRun, ImportRecord
from app.schemas.forecasts import (
    ForecastEvaluation,
    ForecastPointOut,
    ForecastRequest,
    ForecastSeries,
)
from app.services.analytics import BUSINESS_KEY

MONEY = Decimal("0.000001")
PERCENT = Decimal("0.001")
ZERO = Decimal("0.000000")

MAX_MONEY = Decimal("1000000000000")


@dataclass(frozen=True, slots=True)
class ForecastScope:
    currency: str | None = None
    provider: str | None = None
    account_id: str | None = None
    service: str | None = None
    region: str | None = None
    environment: str | None = None
    project: str | None = None


@dataclass(slots=True)
class ForecastOutcome:
    run: ForecastRun
    series: list[ForecastSeries] = field(default_factory=list)


@dataclass(slots=True)
class _DailySeries:
    currency: str
    start: date
    end: date
    values: list[Decimal]
    row_count: int

    @property
    def days(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class _ModelConfig:
    horizon_days: int
    holdout_days: int
    method: ForecastMethod
    moving_average_days: int
    season_length_days: int
    interval_quantile: Decimal
    warning_history_days: int
    min_history_days: int


def run_forecast(
    db: Session,
    settings: Settings,
    scope: ForecastScope,
    request: ForecastRequest,
) -> ForecastOutcome:
    started = time.perf_counter()
    config = _config(settings, request)

    currency = scope.currency.upper() if scope.currency else None
    filters = _filters(scope, currency)
    dedupe = _dedupe_clause(filters)
    reference_date = db.scalar(select(func.max(CostRecord.usage_date)).where(*filters, dedupe))
    if reference_date is None:
        raise AppError(
            "No billing rows match the requested scope; import billing data first.",
            code="no_billing_data",
            status_code=409,
        )

    series_by_currency, cost_rows = _load_series(db, filters, dedupe, settings)
    stored_count = int(db.scalar(select(func.count(CostRecord.id)).where(*filters)) or 0)
    deduped_count = int(
        db.scalar(select(func.count(CostRecord.id)).where(*filters, dedupe)) or 0
    )
    contains_sample = _contains_sample_data(db, filters, dedupe)

    skipped: dict[str, str] = {}
    series: list[ForecastSeries] = []
    points: list[ForecastPoint] = []
    evaluation: dict[str, Any] = {}

    for code in sorted(series_by_currency):
        daily = series_by_currency[code]
        reason = _skip_reason(daily, config)
        if reason is not None:
            skipped[code] = reason
            continue

        built = _build_series(daily, config)
        series.append(built)
        evaluation[code] = _stored_series(built)
        points.extend(
            ForecastPoint(
                run_id=0,
                currency=code,
                period=point.period,
                predicted_cost=point.predicted_cost,
                lower_bound=point.lower_bound,
                upper_bound=point.upper_bound,
                method=config.method,
            )
            for point in built.points
        )

    if not series:
        raise AppError(
            "Not enough history to produce a defensible forecast.",
            code="insufficient_history",
            status_code=409,
            details={
                "min_history_days": settings.forecast_min_history_days,
                "holdout_days": config.holdout_days,
                "skipped": skipped,
            },
        )

    notes = _run_notes(series, skipped, contains_sample)
    warnings = _run_warnings(series, skipped)
    duration_ms = int((time.perf_counter() - started) * 1000)

    run = ForecastRun(
        status="completed",
        method=config.method,
        granularity=ForecastGranularity.DAY,
        reference_date=reference_date,
        history_start=min(item.history_start for item in series),
        history_end=max(item.history_end for item in series),
        horizon_start=min(item.horizon_start for item in series),
        horizon_end=max(item.horizon_end for item in series),
        currency=currency,
        filters=_scope_values(scope, currency),
        config=_stored_config(config, settings),
        series_count=len(series),
        evaluation=evaluation,
        stats={
            "currencies_found": len(series_by_currency),
            "currencies_evaluated": len(series),
            "currencies_skipped": len(skipped),
            "skipped": skipped,
            "daily_groups": cost_rows,
            "stored_cost_rows": stored_count,
            "duplicate_rows_excluded": max(stored_count - deduped_count, 0),
            "contains_sample_data": contains_sample,
        },
        notes=notes,
        warnings=warnings,
        duration_ms=duration_ms,
        completed_at=utcnow(),
    )
    db.add(run)
    db.flush()
    for point in points:
        point.run_id = run.id
        db.add(point)
    db.flush()
    return ForecastOutcome(run=run, series=series)


# -- loading --------------------------------------------------------------
def _load_series(
    db: Session,
    filters: list[Any],
    dedupe: Any,
    settings: Settings,
) -> tuple[dict[str, _DailySeries], int]:
    rows = db.execute(
        select(
            CostRecord.currency,
            CostRecord.usage_date,
            func.count(CostRecord.id).label("row_count"),
            func.coalesce(func.sum(cast(CostRecord.amount, BigInteger)), 0).label("micros"),
        )
        .where(*filters, dedupe)
        .group_by(CostRecord.currency, CostRecord.usage_date)
        .order_by(CostRecord.currency, CostRecord.usage_date)
    ).all()

    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.currency, []).append(row)

    series: dict[str, _DailySeries] = {}
    for currency, currency_rows in grouped.items():
        first_date = currency_rows[0].usage_date
        last_date = currency_rows[-1].usage_date
        start = max(
            first_date,
            last_date - timedelta(days=settings.forecast_max_history_days - 1),
        )
        amounts: dict[date, Decimal] = {}
        row_count = 0
        for row in currency_rows:
            if row.usage_date < start:
                continue
            amounts[row.usage_date] = _micros_to_money(row.micros)
            row_count += int(row.row_count)
        days = (last_date - start).days + 1
        values = [
            amounts.get(start + timedelta(days=offset), ZERO) for offset in range(days)
        ]
        series[currency] = _DailySeries(
            currency=currency,
            start=start,
            end=last_date,
            values=values,
            row_count=row_count,
        )
    return series, len(rows)


def _contains_sample_data(db: Session, filters: list[Any], dedupe: Any) -> bool:
    import_ids = sorted(
        set(db.scalars(select(CostRecord.import_id).where(*filters, dedupe).distinct()))
    )
    if not import_ids:
        return False
    sources = set(
        db.scalars(select(ImportRecord.source).where(ImportRecord.id.in_(import_ids)))
    )
    return "sample" in sources


# -- model ----------------------------------------------------------------
def _config(settings: Settings, request: ForecastRequest) -> _ModelConfig:
    return _ModelConfig(
        horizon_days=request.horizon_days,
        holdout_days=request.holdout_days,
        method=request.method,
        moving_average_days=request.moving_average_days,
        season_length_days=settings.forecast_season_length_days,
        interval_quantile=settings.forecast_interval_quantile,
        warning_history_days=settings.forecast_warning_history_days,
        min_history_days=settings.forecast_min_history_days,
    )


def _skip_reason(daily: _DailySeries, config: _ModelConfig) -> str | None:
    if daily.days < config.min_history_days:
        return "insufficient_history"
    if daily.days <= config.holdout_days:
        return "holdout_too_long"
    train_days = daily.days - config.holdout_days
    if config.method is ForecastMethod.SEASONAL_NAIVE:
        if train_days < config.season_length_days:
            return "insufficient_training_history"
    else:
        if train_days < config.moving_average_days:
            return "moving_average_window_too_long"
    return None


def _build_series(daily: _DailySeries, config: _ModelConfig) -> ForecastSeries:
    train = daily.values[: -config.holdout_days]
    holdout = daily.values[-config.holdout_days :]

    if config.method is ForecastMethod.SEASONAL_NAIVE:
        holdout_predictions = _seasonal_naive(train, len(holdout), config.season_length_days)
        future = _seasonal_naive(daily.values, config.horizon_days, config.season_length_days)
    else:
        holdout_predictions = _moving_average(train, config.moving_average_days, len(holdout))
        future = _moving_average(daily.values, config.moving_average_days, config.horizon_days)
    holdout_predictions = [_money(value) for value in holdout_predictions]
    future = [_money(value) for value in future]

    evaluation = _evaluate(train, holdout, holdout_predictions, daily, config)
    width = evaluation.interval_width
    horizon_start = daily.end + timedelta(days=1)
    points = [
        ForecastPointOut(
            period=horizon_start + timedelta(days=offset),
            predicted_cost=value,
            lower_bound=_clamp(value - width),
            upper_bound=_money(value + width),
        )
        for offset, value in enumerate(future)
    ]
    projected_total = _money(sum(future, Decimal(0)))
    projected_lower = _money(sum((point.lower_bound for point in points), Decimal(0)))
    projected_upper = _money(sum((point.upper_bound for point in points), Decimal(0)))

    return ForecastSeries(
        currency=daily.currency,
        history_start=daily.start,
        history_end=daily.end,
        horizon_start=horizon_start,
        horizon_end=points[-1].period,
        history_days=daily.days,
        points=points,
        evaluation=evaluation,
        projected_total=projected_total,
        projected_lower=projected_lower,
        projected_upper=projected_upper,
        notes=_series_notes(daily, config, evaluation),
    )


def _seasonal_naive(history: list[Decimal], horizon: int, season: int) -> list[Decimal]:
    known = list(history)
    forecast: list[Decimal] = []
    for _ in range(horizon):
        value = known[-season]
        forecast.append(value)
        known.append(value)
    return forecast


def _moving_average(history: list[Decimal], window: int, horizon: int) -> list[Decimal]:
    value = _mean(history[-window:])
    return [value] * horizon


def _evaluate(
    train: list[Decimal],
    holdout: list[Decimal],
    predictions: list[Decimal],
    daily: _DailySeries,
    config: _ModelConfig,
) -> ForecastEvaluation:
    errors = [
        actual - predicted
        for actual, predicted in zip(holdout, predictions, strict=True)
    ]
    absolute = [abs(error) for error in errors]
    mae = _money(_mean(absolute))
    rmse = _money((_mean([error * error for error in errors])).sqrt())
    bias = _signed_money(_mean(errors))
    non_zero = [
        (abs(error), actual)
        for error, actual in zip(errors, holdout, strict=True)
        if actual != 0
    ]
    mape = None
    if non_zero:
        mape = (
            _mean([abs_error / actual for abs_error, actual in non_zero]) * 100
        ).quantize(PERCENT, rounding=ROUND_HALF_UP)
    width = _money(_quantile(absolute, config.interval_quantile))
    confidence = _confidence(daily.days, mape)
    return ForecastEvaluation(
        method=config.method,
        history_days=daily.days,
        train_days=len(train),
        holdout_days=len(holdout),
        evaluated_points=len(holdout),
        mae=mae,
        rmse=rmse,
        bias=bias,
        mape_pct=mape,
        mape_excluded_points=len(holdout) - len(non_zero),
        interval_quantile=config.interval_quantile,
        interval_width=width,
        confidence=confidence,
        warnings=_evaluation_warnings(daily, config, mape, width, len(non_zero), len(holdout)),
    )


def _confidence(history_days: int, mape: Decimal | None) -> ConfidenceLevel:
    if history_days >= 90 and mape is not None and mape <= Decimal("15"):
        return ConfidenceLevel.HIGH
    if history_days >= 42 and mape is not None and mape <= Decimal("30"):
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _evaluation_warnings(
    daily: _DailySeries,
    config: _ModelConfig,
    mape: Decimal | None,
    width: Decimal,
    non_zero: int,
    total: int,
) -> list[str]:
    warnings: list[str] = []
    if daily.days < config.warning_history_days:
        warnings.append(
            f"Only {daily.days} days of history; the forecast should be treated as indicative."
        )
    if config.holdout_days < 14:
        warnings.append(
            f"The holdout is only {config.holdout_days} days, so the error estimate is noisy."
        )
    if mape is None:
        warnings.append("MAPE is unavailable because every holdout actual was zero.")
    elif non_zero < total:
        warnings.append(
            f"{total - non_zero} holdout point(s) with zero actual spend were excluded from MAPE."
        )
    if width == 0:
        warnings.append(
            "Holdout residuals were all zero; the interval is degenerate and likely optimistic."
        )
    if config.horizon_days > config.holdout_days:
        warnings.append(
            f"The interval is estimated from a {config.holdout_days}-day holdout and may "
            f"understate uncertainty over the {config.horizon_days}-day horizon."
        )
    if config.method is ForecastMethod.MOVING_AVERAGE:
        warnings.append(
            "A moving average produces a flat forecast and does not model weekly seasonality."
        )
    return warnings


def _quantile(values: list[Decimal], quantile: Decimal) -> Decimal:
    if not values:
        return ZERO
    ordered = sorted(values)
    rank = int((quantile * len(ordered)).to_integral_value(rounding=ROUND_CEILING))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


# -- persistence helpers --------------------------------------------------
def _stored_series(series: ForecastSeries) -> dict[str, Any]:
    payload = series.model_dump(mode="json")
    payload.pop("currency")
    payload.pop("points")
    return payload


def series_from_run(db: Session, run: ForecastRun, points: list[ForecastPoint]) -> list[ForecastSeries]:
    grouped: dict[str, list[ForecastPoint]] = {}
    for point in points:
        grouped.setdefault(point.currency, []).append(point)
    series: list[ForecastSeries] = []
    for currency in sorted(run.evaluation):
        meta = dict(run.evaluation[currency])
        ordered = sorted(grouped.get(currency, []), key=lambda item: item.period)
        series.append(
            ForecastSeries(
                currency=currency,
                **meta,
                points=[
                    ForecastPointOut(
                        period=point.period,
                        predicted_cost=point.predicted_cost,
                        lower_bound=point.lower_bound,
                        upper_bound=point.upper_bound,
                    )
                    for point in ordered
                ],
            )
        )
    return series


# -- shared helpers -------------------------------------------------------
def _filters(scope: ForecastScope, currency: str | None) -> list[Any]:
    filters: list[Any] = []
    values = {
        CostRecord.currency: currency,
        CostRecord.provider: scope.provider,
        CostRecord.account_id: scope.account_id,
        CostRecord.service: scope.service,
        CostRecord.region: scope.region,
        CostRecord.environment: scope.environment,
        CostRecord.project: scope.project,
    }
    for column, value in values.items():
        if value:
            filters.append(column == value)
    return filters


def _scope_values(scope: ForecastScope, currency: str | None) -> dict[str, str]:
    values = {
        "currency": currency,
        "provider": scope.provider,
        "account_id": scope.account_id,
        "service": scope.service,
        "region": scope.region,
        "environment": scope.environment,
        "project": scope.project,
    }
    return {key: value for key, value in values.items() if value}


def _dedupe_clause(filters: list[Any]) -> Any:
    keep_first = (
        select(func.min(CostRecord.id))
        .where(*filters)
        .group_by(*BUSINESS_KEY)
        .scalar_subquery()
    )
    return CostRecord.id.in_(keep_first)


def _stored_config(config: _ModelConfig, settings: Settings) -> dict[str, Any]:
    return {
        "horizon_days": config.horizon_days,
        "holdout_days": config.holdout_days,
        "method": config.method.value,
        "moving_average_days": config.moving_average_days,
        "season_length_days": config.season_length_days,
        "interval_quantile": str(config.interval_quantile),
        "min_history_days": settings.forecast_min_history_days,
        "max_history_days": settings.forecast_max_history_days,
        "warning_history_days": config.warning_history_days,
        "business_key": [
            "usage_date",
            "provider",
            "account_id",
            "service",
            "resource_id",
            "usage_unit",
            "amount",
        ],
    }


def _series_notes(
    daily: _DailySeries, config: _ModelConfig, evaluation: ForecastEvaluation
) -> list[str]:
    notes = [
        (
            f"Daily spend is de-duplicated billing for {daily.currency}; "
            "calendar days with no billing rows are treated as zero."
        ),
        (
            "The forecast uses only prior spend. The holdout was predicted without "
            "using its actual values."
        ),
        (
            f"The interval is the empirical {evaluation.interval_quantile * 100}% quantile "
            "of absolute holdout residuals, not a guaranteed range."
        ),
    ]
    if config.method is ForecastMethod.SEASONAL_NAIVE:
        notes.append(
            f"Seasonal naive predicts each day from the same weekday "
            f"{config.season_length_days} days earlier, recursively beyond that."
        )
    else:
        notes.append(
            f"Moving average uses the flat mean of the last {config.moving_average_days} days."
        )
    return notes


def _run_notes(
    series: list[ForecastSeries],
    skipped: dict[str, str],
    contains_sample: bool,
) -> list[str]:
    notes = [
        "Forecasts are deterministic statistical baselines; no AI or cloud API is used.",
        "Each currency is forecast separately; projected totals are never combined.",
        "Missing calendar days with no billing rows are treated as zero spend.",
        "Prediction intervals are empirical from held-out residuals and are not guarantees.",
    ]
    if len(series) > 1:
        notes.append("Multiple currencies are present and must not be added together.")
    if skipped:
        notes.append(
            "Some currencies were skipped because their history was insufficient or the "
            "model window did not fit; see stats.skipped."
        )
    if contains_sample:
        notes.append("Billing includes synthetic sample data; these are demo forecasts.")
    return notes


def _run_warnings(series: list[ForecastSeries], skipped: dict[str, str]) -> list[str]:
    warnings = [
        "A statistical baseline can be wrong; use the held-out error metrics and interval.",
    ]
    if any(item.evaluation.mape_pct is None for item in series):
        warnings.append("MAPE is unavailable for at least one currency.")
    if any(item.evaluation.confidence is ConfidenceLevel.LOW for item in series):
        warnings.append("At least one currency has low forecast confidence.")
    if skipped:
        warnings.append(
            f"{len(skipped)} currency series could not be evaluated: "
            + ", ".join(f"{code}={reason}" for code, reason in sorted(skipped.items()))
        )
    return warnings


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return ZERO
    return sum(values, Decimal(0)) / len(values)


def _micros_to_money(micros: int | None) -> Decimal:
    """Convert a stored scaled ``BIGINT`` (6 dp) into an exact ``Decimal``."""
    return Decimal(int(micros or 0)).scaleb(-6)


def _money(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise AppError("A non-finite value reached the forecast.", code="invalid_forecast")
    bounded = max(min(value, MAX_MONEY), Decimal(0))
    return bounded.quantize(MONEY, rounding=ROUND_HALF_UP)


def _signed_money(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise AppError("A non-finite value reached the forecast.", code="invalid_forecast")
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _clamp(value: Decimal) -> Decimal:
    return _money(max(value, Decimal(0)))
