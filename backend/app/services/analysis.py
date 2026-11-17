"""Deterministic waste detection and reproducible savings scenarios.

The engine is intentionally simple, explainable and local:

* idle resources are billing baselines with near-zero observed CPU and memory;
* rightsizing compares two exact catalogue prices for the same provider,
  region, currency and usage unit;
* every number comes from imported billing rows or a sourced price entry.

It never calls a cloud API, never changes a resource and never guesses a price.
Low utilization is treated as a review signal, not as proof of waste.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import (
    ConfidenceLevel,
    FindingStatus,
    FindingType,
    RiskLevel,
    ScenarioMethod,
)
from app.core.errors import AppError
from app.core.time import utcnow
from app.db.models import (
    AnalysisRun,
    CostRecord,
    Finding,
    ImportRecord,
    PriceEntry,
    ResourceMetric,
    SavingsScenario,
)
from app.services.analytics import BUSINESS_KEY
from app.services.prices import find_price

MONEY = Decimal("0.000001")
PERCENT = Decimal("0.001")
EVIDENCE_LIMIT = 50
SAMPLE_SOURCE = "sample"


@dataclass(frozen=True, slots=True)
class AnalysisScope:
    currency: str | None = None
    provider: str | None = None
    account_id: str | None = None
    service: str | None = None
    region: str | None = None
    environment: str | None = None
    project: str | None = None


@dataclass(slots=True)
class FindingBundle:
    finding: Finding
    scenario: SavingsScenario


@dataclass(slots=True)
class AnalysisOutcome:
    run: AnalysisRun
    bundles: list[FindingBundle] = field(default_factory=list)


@dataclass(slots=True)
class _MetricStats:
    sample_count: int
    observation_days: int
    observation_start: datetime
    observation_end: datetime
    cpu_avg_pct: Decimal
    cpu_p95_max_pct: Decimal
    memory_avg_pct: Decimal
    memory_p95_max_pct: Decimal
    sample_ids: list[int]


@dataclass(slots=True)
class _ResourceCosts:
    rows: list[CostRecord]
    baseline: Decimal

    @property
    def currency(self) -> str:
        return self.rows[0].currency

    @property
    def skus(self) -> set[str]:
        return {row.sku for row in self.rows if row.sku}


def run_analysis(db: Session, settings: Settings, scope: AnalysisScope) -> AnalysisOutcome:
    started = time.perf_counter()
    currency = scope.currency.upper() if scope.currency else None
    base_filters = _filters(scope, currency)

    reference_date = db.scalar(select(func.max(CostRecord.usage_date)).where(*base_filters))
    if reference_date is None:
        raise AppError(
            "No billing rows match the requested scope; import billing data first.",
            code="no_billing_data",
            status_code=409,
        )

    window_end = reference_date
    window_start = window_end - timedelta(days=settings.analysis_cost_days - 1)
    window_filters = [*base_filters, CostRecord.usage_date.between(window_start, window_end)]
    dedupe = _dedupe_clause(window_filters)
    rows = list(
        db.scalars(
            select(CostRecord)
            .where(*window_filters, dedupe)
            .order_by(CostRecord.resource_id, CostRecord.usage_date, CostRecord.id)
        )
    )
    stored_count = int(
        db.scalar(select(func.count(CostRecord.id)).where(*window_filters)) or 0
    )
    excluded_duplicates = max(stored_count - len(rows), 0)

    grouped: dict[str, list[CostRecord]] = {}
    for row in rows:
        grouped.setdefault(row.resource_id, []).append(row)

    sample_import_ids = set(
        db.scalars(select(ImportRecord.id).where(ImportRecord.source == SAMPLE_SOURCE))
    )
    metrics_by_resource = _load_metrics(
        db,
        list(grouped),
        start=datetime.combine(window_start, dt_time.min, tzinfo=UTC),
        end=datetime.combine(window_end + timedelta(days=1), dt_time.min, tzinfo=UTC),
    )

    skipped: dict[str, int] = {
        "no_utilization": 0,
        "insufficient_observation": 0,
        "mixed_currency": 0,
        "missing_sku": 0,
        "mixed_sku": 0,
        "missing_price": 0,
        "below_min_savings": 0,
    }
    bundles: list[FindingBundle] = []

    for resource_id in sorted(grouped):
        resource_rows = grouped[resource_id]
        resource = _ResourceCosts(
            rows=resource_rows,
            baseline=_sum_amounts(resource_rows),
        )
        if resource.baseline <= 0:
            continue
        if len({row.currency for row in resource_rows}) > 1:
            skipped["mixed_currency"] += 1
            continue

        samples = metrics_by_resource.get(resource_id, [])
        if not samples:
            skipped["no_utilization"] += 1
            continue
        stats = _metric_stats(samples)
        if (
            stats.observation_days < settings.min_observation_days
            or stats.sample_count < settings.min_samples
        ):
            skipped["insufficient_observation"] += 1
            continue

        sample_data = bool({row.import_id for row in resource_rows} & sample_import_ids) or bool(
            {row.import_id for row in samples} & sample_import_ids
        )
        finding_type = _classify(stats, settings)
        if finding_type is FindingType.IDLE_RESOURCE:
            bundle = _idle_finding(
                db,
                settings=settings,
                resource=resource,
                stats=stats,
                window_start=window_start,
                window_end=window_end,
                sample_data=sample_data,
            )
        elif finding_type is FindingType.OVER_PROVISIONED:
            bundle = _rightsize_finding(
                db,
                settings=settings,
                resource=resource,
                stats=stats,
                window_start=window_start,
                window_end=window_end,
                sample_data=sample_data,
                skipped=skipped,
            )
        else:
            continue

        if bundle is not None:
            bundles.append(bundle)

    notes = _notes(bundles, skipped)
    uses_synthetic = any(bundle.finding.uses_synthetic_prices for bundle in bundles)
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for bundle in bundles:
        finding = bundle.finding
        totals[finding.currency] = totals.get(finding.currency, Decimal(0)) + (
            finding.estimated_monthly_savings
        )
        counts[finding.finding_type.value] = counts.get(finding.finding_type.value, 0) + 1

    duration_ms = int((time.perf_counter() - started) * 1000)
    run = AnalysisRun(
        status="completed",
        reference_date=reference_date,
        cost_window_start=window_start,
        cost_window_end=window_end,
        currency=currency,
        filters=_scope_values(scope, currency),
        rule_config=_rule_config(settings),
        finding_count=len(bundles),
        total_savings_by_currency={
            code: str(_money(amount)) for code, amount in sorted(totals.items())
        },
        uses_synthetic_prices=uses_synthetic,
        notes=notes,
        stats={
            "resources_with_costs": len(grouped),
            "resources_with_utilization": len(metrics_by_resource),
            "cost_rows_examined": len(rows),
            "duplicate_rows_excluded": excluded_duplicates,
            "findings_by_type": counts,
            "skipped": {key: value for key, value in skipped.items() if value},
        },
        duration_ms=duration_ms,
        completed_at=utcnow(),
    )
    db.add(run)
    db.flush()

    for bundle in bundles:
        bundle.finding.run_id = run.id
        bundle.scenario.finding_id = 0  # assigned after the finding is flushed
        db.add(bundle.finding)
        db.flush()
        bundle.scenario.finding_id = bundle.finding.id
        db.add(bundle.scenario)
    db.flush()

    return AnalysisOutcome(run=run, bundles=bundles)


# -- rules ----------------------------------------------------------------
def _classify(stats: _MetricStats, settings: Settings) -> FindingType | None:
    if (
        stats.cpu_p95_max_pct < settings.idle_cpu_p95_pct
        and stats.memory_p95_max_pct < settings.idle_memory_p95_pct
    ):
        return FindingType.IDLE_RESOURCE
    if (
        stats.cpu_avg_pct < settings.rightsize_cpu_avg_pct
        and stats.memory_avg_pct < settings.rightsize_memory_avg_pct
    ):
        return FindingType.OVER_PROVISIONED
    return None


def _idle_finding(
    db: Session,
    *,
    settings: Settings,
    resource: _ResourceCosts,
    stats: _MetricStats,
    window_start: date,
    window_end: date,
    sample_data: bool,
) -> FindingBundle | None:
    if resource.baseline < settings.min_monthly_savings:
        return None

    row = resource.rows[0]
    assumptions = [
        (
            f"Baseline is {resource.currency} {_money(resource.baseline)} of de-duplicated "
            f"imported billing from {window_start.isoformat()} to {window_end.isoformat()}; "
            "no FX conversion is applied."
        ),
        (
            f"Savings assume the resource is stopped for the entire {settings.analysis_cost_days}-day "
            "window and no replacement resource is provisioned."
        ),
        (
            f"Utilization comes from {stats.sample_count} imported samples across "
            f"{stats.observation_days} day(s). Maximum observed CPU p95 is "
            f"{stats.cpu_p95_max_pct}% and memory p95 is {stats.memory_p95_max_pct}%."
        ),
        "Low utilization is not proof of waste; an owner must confirm the workload can be stopped.",
    ]
    warnings = [
        "Owner review is required before stopping this resource.",
        "Stopping may break dependent workloads, scheduled jobs or data access.",
    ]
    if sample_data:
        warnings.append("Billing and utilization are synthetic sample data, not a real environment.")

    finding = Finding(
        run_id=0,
        finding_type=FindingType.IDLE_RESOURCE,
        status=FindingStatus.OPEN,
        provider=row.provider,
        account_id=row.account_id,
        service=row.service,
        resource_id=row.resource_id,
        region=row.region,
        environment=row.environment,
        project=row.project,
        currency=resource.currency,
        current_sku=next(iter(resource.skus), None) if len(resource.skus) == 1 else None,
        recommended_sku=None,
        baseline_monthly_cost=_money(resource.baseline),
        proposed_monthly_cost=Decimal("0.000000"),
        estimated_monthly_savings=_money(resource.baseline),
        savings_pct=Decimal("100.000"),
        confidence=_confidence(stats, window_start, window_end),
        risk=_risk(row.environment, FindingType.IDLE_RESOURCE),
        cost_window_start=window_start,
        cost_window_end=window_end,
        observation_start=stats.observation_start,
        observation_end=stats.observation_end,
        observation_days=stats.observation_days,
        sample_count=stats.sample_count,
        metrics=_metric_payload(stats),
        evidence=_evidence(resource, stats),
        assumptions=assumptions,
        warnings=warnings,
        price_source={},
        uses_synthetic_prices=False,
    )
    scenario = SavingsScenario(
        finding_id=0,
        method=ScenarioMethod.STOP_RESOURCE,
        currency=resource.currency,
        baseline_monthly_cost=finding.baseline_monthly_cost,
        proposed_monthly_cost=finding.proposed_monthly_cost,
        estimated_monthly_savings=finding.estimated_monthly_savings,
        assumptions=assumptions,
    )
    return FindingBundle(finding=finding, scenario=scenario)


def _rightsize_finding(
    db: Session,
    *,
    settings: Settings,
    resource: _ResourceCosts,
    stats: _MetricStats,
    window_start: date,
    window_end: date,
    sample_data: bool,
    skipped: dict[str, int],
) -> FindingBundle | None:
    row = resource.rows[0]
    skus = resource.skus
    if not skus:
        skipped["missing_sku"] += 1
        return None
    if len(skus) > 1:
        skipped["mixed_sku"] += 1
        return None
    current_sku = next(iter(skus))

    current_price = find_price(
        db,
        provider=row.provider,
        sku=current_sku,
        region=row.region,
        currency=resource.currency,
        usage_unit=row.usage_unit,
        on_date=window_end,
    )
    if current_price is None or not current_price.replacement_sku:
        skipped["missing_price"] += 1
        return None
    replacement_sku = current_price.replacement_sku
    replacement_price = find_price(
        db,
        provider=row.provider,
        sku=replacement_sku,
        region=row.region,
        currency=resource.currency,
        usage_unit=row.usage_unit,
        on_date=window_end,
    )
    if replacement_price is None:
        skipped["missing_price"] += 1
        return None

    proposed = _money(resource.baseline * replacement_price.unit_price / current_price.unit_price)
    savings = _money(resource.baseline - proposed)
    if savings < settings.min_monthly_savings:
        skipped["below_min_savings"] += 1
        return None
    savings_pct = (savings / resource.baseline * 100).quantize(PERCENT, rounding=ROUND_HALF_UP)
    uses_synthetic = current_price.is_synthetic or replacement_price.is_synthetic
    full_coverage = _covers(current_price, window_start, window_end) and _covers(
        replacement_price, window_start, window_end
    )
    confidence = _confidence(stats, window_start, window_end)
    if not full_coverage:
        confidence = _downgrade(confidence)

    assumptions = [
        (
            f"Baseline is {resource.currency} {_money(resource.baseline)} of de-duplicated "
            f"imported billing from {window_start.isoformat()} to {window_end.isoformat()}."
        ),
        (
            f"Proposed cost scales the baseline by the catalogue price ratio "
            f"{replacement_sku} / {current_sku} = {replacement_price.unit_price} / "
            f"{current_price.unit_price} for the same provider, region, currency and usage unit."
        ),
        (
            f"Prices are effective on {window_end.isoformat()} from "
            f"'{replacement_price.source_name}'. No FX conversion or negotiated discount is applied."
        ),
        (
            "No performance, network or storage requirement is modelled; the smaller SKU must be "
            "validated by the resource owner."
        ),
    ]
    warnings = [
        "Owner review is required before changing the resource size.",
        "Price-list savings are an estimate, not a confirmed invoice reduction.",
    ]
    if not full_coverage:
        warnings.append(
            "The catalogue price entry does not cover the whole cost window; confidence was downgraded."
        )
    if uses_synthetic:
        warnings.append(
            "The price catalogue is synthetic demo data, not a vendor price list or quote."
        )
    if sample_data:
        warnings.append("Billing and utilization are synthetic sample data, not a real environment.")

    price_source = {
        "current": _price_payload(current_price),
        "replacement": _price_payload(replacement_price),
    }
    finding = Finding(
        run_id=0,
        finding_type=FindingType.OVER_PROVISIONED,
        status=FindingStatus.OPEN,
        provider=row.provider,
        account_id=row.account_id,
        service=row.service,
        resource_id=row.resource_id,
        region=row.region,
        environment=row.environment,
        project=row.project,
        currency=resource.currency,
        current_sku=current_sku,
        recommended_sku=replacement_sku,
        baseline_monthly_cost=_money(resource.baseline),
        proposed_monthly_cost=proposed,
        estimated_monthly_savings=savings,
        savings_pct=savings_pct,
        confidence=confidence,
        risk=_risk(row.environment, FindingType.OVER_PROVISIONED),
        cost_window_start=window_start,
        cost_window_end=window_end,
        observation_start=stats.observation_start,
        observation_end=stats.observation_end,
        observation_days=stats.observation_days,
        sample_count=stats.sample_count,
        metrics=_metric_payload(stats),
        evidence=_evidence(resource, stats, price_ids=[current_price.id, replacement_price.id]),
        assumptions=assumptions,
        warnings=warnings,
        price_source=price_source,
        uses_synthetic_prices=uses_synthetic,
    )
    scenario = SavingsScenario(
        finding_id=0,
        method=ScenarioMethod.RIGHTSIZE_SKU,
        currency=resource.currency,
        baseline_monthly_cost=finding.baseline_monthly_cost,
        proposed_monthly_cost=finding.proposed_monthly_cost,
        estimated_monthly_savings=finding.estimated_monthly_savings,
        assumptions=assumptions,
    )
    return FindingBundle(finding=finding, scenario=scenario)


# -- lookups and helpers --------------------------------------------------
def _filters(scope: AnalysisScope, currency: str | None) -> list[Any]:
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


def _scope_values(scope: AnalysisScope, currency: str | None) -> dict[str, str]:
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


def _rule_config(settings: Settings) -> dict[str, Any]:
    return {
        "idle_cpu_p95_pct": str(settings.idle_cpu_p95_pct),
        "idle_memory_p95_pct": str(settings.idle_memory_p95_pct),
        "rightsize_cpu_avg_pct": str(settings.rightsize_cpu_avg_pct),
        "rightsize_memory_avg_pct": str(settings.rightsize_memory_avg_pct),
        "min_observation_days": settings.min_observation_days,
        "min_samples": settings.min_samples,
        "analysis_cost_days": settings.analysis_cost_days,
        "min_monthly_savings": str(settings.min_monthly_savings),
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


def _dedupe_clause(filters: list[Any]) -> Any:
    keep_first = (
        select(func.min(CostRecord.id))
        .where(*filters)
        .group_by(*BUSINESS_KEY)
        .scalar_subquery()
    )
    return CostRecord.id.in_(keep_first)


def _load_metrics(
    db: Session,
    resource_ids: list[str],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, list[ResourceMetric]]:
    if not resource_ids:
        return {}
    rows = db.scalars(
        select(ResourceMetric)
        .where(
            ResourceMetric.resource_id.in_(resource_ids),
            ResourceMetric.observed_at >= start,
            ResourceMetric.observed_at < end,
        )
        .order_by(ResourceMetric.resource_id, ResourceMetric.observed_at)
    )
    grouped: dict[str, list[ResourceMetric]] = {}
    for row in rows:
        grouped.setdefault(row.resource_id, []).append(row)
    return grouped


def _metric_stats(samples: list[ResourceMetric]) -> _MetricStats:
    count = len(samples)
    observation_days = len({sample.observed_at.date() for sample in samples})
    return _MetricStats(
        sample_count=count,
        observation_days=observation_days,
        observation_start=samples[0].observed_at,
        observation_end=samples[-1].observed_at,
        cpu_avg_pct=_average([sample.cpu_avg_pct for sample in samples]),
        cpu_p95_max_pct=max(sample.cpu_p95_pct for sample in samples),
        memory_avg_pct=_average([sample.memory_avg_pct for sample in samples]),
        memory_p95_max_pct=max(sample.memory_p95_pct for sample in samples),
        sample_ids=[sample.id for sample in samples],
    )


def _average(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0.000")
    return (sum(values, Decimal(0)) / len(values)).quantize(PERCENT, rounding=ROUND_HALF_UP)


def _sum_amounts(rows: list[CostRecord]) -> Decimal:
    return _money(sum((row.amount for row in rows), Decimal(0)))


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _metric_payload(stats: _MetricStats) -> dict[str, Any]:
    return {
        "cpu_avg_pct": str(stats.cpu_avg_pct),
        "cpu_p95_max_pct": str(stats.cpu_p95_max_pct),
        "memory_avg_pct": str(stats.memory_avg_pct),
        "memory_p95_max_pct": str(stats.memory_p95_max_pct),
    }


def _evidence(
    resource: _ResourceCosts,
    stats: _MetricStats,
    *,
    price_ids: list[int] | None = None,
) -> dict[str, Any]:
    cost_ids = [row.id for row in resource.rows]
    payload: dict[str, Any] = {
        "cost_record_ids": cost_ids[:EVIDENCE_LIMIT],
        "cost_record_id_count": len(cost_ids),
        "cost_records_truncated": len(cost_ids) > EVIDENCE_LIMIT,
        "metric_ids": stats.sample_ids[:EVIDENCE_LIMIT],
        "metric_id_count": stats.sample_count,
        "metric_ids_truncated": stats.sample_count > EVIDENCE_LIMIT,
        "import_ids": sorted({row.import_id for row in resource.rows}),
    }
    if price_ids:
        payload["price_entry_ids"] = price_ids
    return payload


def _confidence(
    stats: _MetricStats, window_start: date, window_end: date
) -> ConfidenceLevel:
    window_days = max((window_end - window_start).days + 1, 1)
    coverage = Decimal(stats.observation_days) / Decimal(window_days)
    if coverage >= Decimal("0.9"):
        return ConfidenceLevel.HIGH
    if coverage >= Decimal("0.6"):
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _downgrade(level: ConfidenceLevel) -> ConfidenceLevel:
    if level is ConfidenceLevel.HIGH:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _risk(environment: str, finding_type: FindingType) -> RiskLevel:
    if environment == "prod":
        return RiskLevel.HIGH if finding_type is FindingType.IDLE_RESOURCE else RiskLevel.MEDIUM
    return RiskLevel.MEDIUM if finding_type is FindingType.IDLE_RESOURCE else RiskLevel.LOW


def _covers(price: PriceEntry, window_start: date, window_end: date) -> bool:
    return price.effective_from <= window_start and (
        price.effective_to is None or price.effective_to >= window_end
    )


def _price_payload(price: PriceEntry) -> dict[str, Any]:
    return {
        "price_entry_id": price.id,
        "sku": price.sku,
        "display_name": price.display_name,
        "region": price.region,
        "usage_unit": price.usage_unit,
        "unit_price": str(price.unit_price),
        "currency": price.currency,
        "effective_from": price.effective_from.isoformat(),
        "effective_to": price.effective_to.isoformat() if price.effective_to else None,
        "is_synthetic": price.is_synthetic,
        "source_name": price.source_name,
        "source_url": price.source_url,
    }


def _notes(bundles: list[FindingBundle], skipped: dict[str, int]) -> list[str]:
    notes = [
        (
            "Waste detection is rule-based and deterministic; it never calls a cloud API "
            "or changes infrastructure."
        ),
        "Lower utilization alone is not proof of waste; owner review is required before any change.",
        "Savings are exact decimal estimates in the billing currency; no FX conversion is applied.",
    ]
    if any(bundle.finding.uses_synthetic_prices for bundle in bundles):
        notes.append(
            "One or more scenarios use a clearly labelled synthetic demo price catalogue, "
            "not vendor prices or quotes."
        )
    if skipped.get("missing_price") or skipped.get("missing_sku"):
        notes.append(
            "Some low-utilization resources had no exact sourced price and were not turned into "
            "savings scenarios; no price or saving was invented."
        )
    if skipped.get("insufficient_observation") or skipped.get("no_utilization"):
        notes.append(
            "Some resources had insufficient or missing utilization history and were not evaluated."
        )
    if len({bundle.finding.currency for bundle in bundles}) > 1:
        notes.append("Savings are partitioned by currency and must never be added together.")
    if not bundles:
        notes.append("No waste candidates met the configured thresholds for this scope.")
    return notes
