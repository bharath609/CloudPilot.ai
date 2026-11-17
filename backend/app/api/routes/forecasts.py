"""Spend forecast endpoints: run a deterministic baseline and inspect results."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.models import ForecastPoint, ForecastRun
from app.schemas.forecasts import (
    ForecastListResponse,
    ForecastRequest,
    ForecastResult,
    ForecastRunSummary,
)
from app.services.forecasting import (
    ForecastOutcome,
    ForecastScope,
    run_forecast,
    series_from_run,
)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.post(
    "/run",
    response_model=ForecastResult,
    summary="Run a transparent spend forecast with held-out evaluation",
)
def create_forecast(
    payload: ForecastRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ForecastResult:
    values = payload or ForecastRequest()
    scope = ForecastScope(
        currency=values.currency,
        provider=values.provider,
        account_id=values.account_id,
        service=values.service,
        region=values.region,
        environment=values.environment,
        project=values.project,
    )
    try:
        outcome = run_forecast(db, settings, scope, values)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _result(outcome)


@router.get(
    "",
    response_model=ForecastListResponse,
    summary="Forecast results from the latest run (or a specific run)",
)
def list_forecasts(
    run_id: int | None = Query(None, ge=1),
    currency: str | None = Query(None, pattern=r"^[A-Za-z]{3}$"),
    db: Session = Depends(get_db),
) -> ForecastListResponse:
    run = _get_run(db, run_id) if run_id is not None else _latest_run(db)
    if run is None:
        return ForecastListResponse(run=None, series=[], total=0)
    points = list(
        db.scalars(
            select(ForecastPoint)
            .where(ForecastPoint.run_id == run.id)
            .order_by(ForecastPoint.currency, ForecastPoint.period)
        )
    )
    series = series_from_run(db, run, points)
    if currency:
        code = currency.upper()
        series = [item for item in series if item.currency == code]
    return ForecastListResponse(
        run=ForecastRunSummary.model_validate(run),
        series=series,
        total=len(series),
    )


@router.get(
    "/{run_id}",
    response_model=ForecastResult,
    summary="One forecast run with its daily points",
)
def get_forecast(run_id: int, db: Session = Depends(get_db)) -> ForecastResult:
    run = _get_run(db, run_id)
    points = list(
        db.scalars(
            select(ForecastPoint)
            .where(ForecastPoint.run_id == run.id)
            .order_by(ForecastPoint.currency, ForecastPoint.period)
        )
    )
    return ForecastResult(
        run=ForecastRunSummary.model_validate(run),
        series=series_from_run(db, run, points),
    )


# -- helpers --------------------------------------------------------------
def _result(outcome: ForecastOutcome) -> ForecastResult:
    return ForecastResult(
        run=ForecastRunSummary.model_validate(outcome.run),
        series=outcome.series,
    )


def _latest_run(db: Session) -> ForecastRun | None:
    return db.scalar(select(ForecastRun).order_by(ForecastRun.id.desc()).limit(1))


def _get_run(db: Session, run_id: int) -> ForecastRun:
    run = db.get(ForecastRun, run_id)
    if run is None:
        raise NotFoundError(f"Forecast run {run_id} was not found.")
    return run
