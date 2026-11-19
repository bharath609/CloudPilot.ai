"""Read-only resource health aggregation.

Joins utilization samples with de-duplicated billing in one explicit window so a
reviewer can see the observation basis beside each resource. No clouds are
contacted and no action is offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import CostRecord, ImportRecord, ResourceMetric
from app.schemas.resources import (
    ResourceHealthItem,
    ResourceHealthResponse,
    ResourceWindow,
)
from app.services.analytics import BUSINESS_KEY, CostScope

PERCENT_QUANTUM = Decimal("0.001")
DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class _CostInfo:
    currency: str
    amount: Decimal
    provider: str
    service: str
    region: str
    environment: str
    project: str
    owner: str | None
    team: str | None
    other_currencies: int


def resource_health(
    db: Session,
    settings: Settings,
    scope: CostScope,
    *,
    limit: int,
    offset: int,
) -> ResourceHealthResponse:
    window = _window(db, scope)
    metric_rows = _metric_rows(db, scope, window)
    cost_info = _cost_info(db, scope, window)

    grouped: dict[str, list[ResourceMetric]] = {}
    for row in metric_rows:
        grouped.setdefault(row.resource_id, []).append(row)

    items: list[ResourceHealthItem] = []
    for resource_id, samples in grouped.items():
        cost = cost_info.get(resource_id)
        metrics = _stats(samples)
        warnings: list[str] = []
        if cost is None:
            warnings.append("No billing row for this resource in the window; cost is unknown.")
        elif cost.other_currencies:
            warnings.append(
                f"{cost.other_currencies} other currency series exist; cost shows "
                f"{cost.currency} only and is never combined."
            )
        if metrics["observation_days"] < settings.min_observation_days:
            warnings.append(
                f"Observation window is {metrics['observation_days']} day(s); "
                f"{settings.min_observation_days} are required for a finding."
            )
        elif metrics["sample_count"] < settings.min_samples:
            warnings.append(
                f"Only {metrics['sample_count']} sample(s); {settings.min_samples} are "
                "required for a finding."
            )
        if cost is not None and (cost.owner in {None, "unassigned"}):
            warnings.append("No owner tag; assign an owner before any action.")

        eligible = (
            metrics["observation_days"] >= settings.min_observation_days
            and metrics["sample_count"] >= settings.min_samples
        )
        idle = (
            eligible
            and metrics["cpu_p95_max_pct"] < settings.idle_cpu_p95_pct
            and metrics["memory_p95_max_pct"] < settings.idle_memory_p95_pct
        )
        rightsize = (
            eligible
            and metrics["cpu_avg_pct"] < settings.rightsize_cpu_avg_pct
            and metrics["memory_avg_pct"] < settings.rightsize_memory_avg_pct
        )
        items.append(
            ResourceHealthItem(
                resource_id=resource_id,
                provider=cost.provider if cost else "",
                service=cost.service if cost else "",
                region=cost.region if cost else "",
                environment=cost.environment if cost else "",
                project=cost.project if cost else "",
                owner=cost.owner if cost else None,
                team=cost.team if cost else None,
                currency=cost.currency if cost else None,
                window_cost=cost.amount if cost else None,
                **metrics,
                idle_candidate=idle,
                rightsize_candidate=rightsize,
                warnings=warnings,
            )
        )

    items.sort(
        key=lambda item: (
            -(item.window_cost or Decimal("0")),
            item.resource_id,
        )
    )
    total = len(items)
    page = items[offset : offset + limit]
    return ResourceHealthResponse(
        window=window,
        items=page,
        total=total,
        limit=limit,
        offset=offset,
        thresholds={
            "idle_cpu_p95_pct": str(settings.idle_cpu_p95_pct),
            "idle_memory_p95_pct": str(settings.idle_memory_p95_pct),
            "rightsize_cpu_avg_pct": str(settings.rightsize_cpu_avg_pct),
            "rightsize_memory_avg_pct": str(settings.rightsize_memory_avg_pct),
            "min_observation_days": str(settings.min_observation_days),
            "min_samples": str(settings.min_samples),
        },
        contains_sample_data=_contains_sample(db, scope, window),
        notes=_notes(total, window),
    )


def _window(db: Session, scope: CostScope) -> ResourceWindow:
    latest_metric = db.scalar(
        select(ResourceMetric.observed_at).order_by(ResourceMetric.observed_at.desc()).limit(1)
    )
    latest_cost = db.scalar(
        select(CostRecord.usage_date).order_by(CostRecord.usage_date.desc()).limit(1)
    )
    candidates = [
        value
        for value in (
            latest_metric.date() if latest_metric else None,
            latest_cost if latest_cost else None,
            scope.end,
        )
        if value is not None
    ]
    if scope.end is not None:
        end = scope.end
    elif candidates:
        end = max(candidates)
    else:
        end = datetime.now(UTC).date()
    start = scope.start or (end - timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    if start > end:
        raise AppError(
            "'start' must be on or before 'end'.",
            code="invalid_date_range",
            status_code=400,
            details={"start": start.isoformat(), "end": end.isoformat()},
        )
    return ResourceWindow(start=start, end=end, days=(end - start).days + 1)


def _metric_rows(
    db: Session, scope: CostScope, window: ResourceWindow
) -> list[ResourceMetric]:
    start = datetime.combine(window.start, time.min, tzinfo=UTC)
    end = datetime.combine(window.end + timedelta(days=1), time.min, tzinfo=UTC)
    stmt = select(ResourceMetric).where(
        ResourceMetric.observed_at >= start,
        ResourceMetric.observed_at < end,
    )
    scope_filters: list[Any] = []
    if scope.currency:
        scope_filters.append(CostRecord.currency == scope.currency)
    if scope.provider:
        scope_filters.append(CostRecord.provider == scope.provider)
    if scope.account_id:
        scope_filters.append(CostRecord.account_id == scope.account_id)
    if scope.service:
        scope_filters.append(CostRecord.service == scope.service)
    if scope.region:
        scope_filters.append(CostRecord.region == scope.region)
    if scope.environment:
        scope_filters.append(CostRecord.environment == scope.environment)
    if scope.project:
        scope_filters.append(CostRecord.project == scope.project)
    if scope_filters:
        stmt = stmt.where(
            ResourceMetric.resource_id.in_(
                select(CostRecord.resource_id).where(*scope_filters)
            )
        )
    return list(db.scalars(stmt.order_by(ResourceMetric.resource_id, ResourceMetric.observed_at)))


def _cost_info(
    db: Session, scope: CostScope, window: ResourceWindow
) -> dict[str, _CostInfo]:
    filters: list[Any] = [CostRecord.usage_date.between(window.start, window.end)]
    if scope.currency:
        filters.append(CostRecord.currency == scope.currency)
    if scope.provider:
        filters.append(CostRecord.provider == scope.provider)
    if scope.service:
        filters.append(CostRecord.service == scope.service)
    if scope.region:
        filters.append(CostRecord.region == scope.region)
    if scope.environment:
        filters.append(CostRecord.environment == scope.environment)
    if scope.project:
        filters.append(CostRecord.project == scope.project)
    keep_first = (
        select(func.min(CostRecord.id))
        .where(*filters)
        .group_by(*BUSINESS_KEY)
        .scalar_subquery()
    )
    rows = db.execute(
        select(
            CostRecord.resource_id,
            CostRecord.currency,
            func.coalesce(func.sum(cast(CostRecord.amount, BigInteger)), 0).label("micros"),
        )
        .where(*filters, CostRecord.id.in_(keep_first))
        .group_by(CostRecord.resource_id, CostRecord.currency)
    ).all()
    totals: dict[str, list[tuple[str, Decimal]]] = {}
    for row in rows:
        amount = Decimal(int(row.micros)).scaleb(-6)
        totals.setdefault(row.resource_id, []).append((row.currency, amount))

    latest = db.execute(
        select(CostRecord)
        .where(*filters)
        .order_by(CostRecord.resource_id, CostRecord.usage_date.desc(), CostRecord.id.desc())
    ).scalars()
    meta: dict[str, CostRecord] = {}
    for record in latest:
        meta.setdefault(record.resource_id, record)

    info: dict[str, _CostInfo] = {}
    for resource_id, series in totals.items():
        series.sort(key=lambda item: (-item[1], item[0]))
        currency, amount = series[0]
        latest_record = meta.get(resource_id)
        tags = latest_record.tags if latest_record is not None else {}
        info[resource_id] = _CostInfo(
            currency=currency,
            amount=amount,
            provider=latest_record.provider if latest_record else "",
            service=latest_record.service if latest_record else "",
            region=latest_record.region if latest_record else "",
            environment=latest_record.environment if latest_record else "",
            project=latest_record.project if latest_record else "",
            owner=tags.get("owner") if isinstance(tags, dict) else None,
            team=tags.get("team") if isinstance(tags, dict) else None,
            other_currencies=len(series) - 1,
        )
    return info


def _stats(samples: list[ResourceMetric]) -> dict[str, Any]:
    count = len(samples)
    cpu_avg = _average([sample.cpu_avg_pct for sample in samples])
    memory_avg = _average([sample.memory_avg_pct for sample in samples])
    return {
        "observation_start": samples[0].observed_at,
        "observation_end": samples[-1].observed_at,
        "observation_days": len({sample.observed_at.date() for sample in samples}),
        "sample_count": count,
        "cpu_avg_pct": cpu_avg,
        "cpu_p95_max_pct": max(sample.cpu_p95_pct for sample in samples),
        "memory_avg_pct": memory_avg,
        "memory_p95_max_pct": max(sample.memory_p95_pct for sample in samples),
        "network_in_bytes": sum(sample.network_in_bytes for sample in samples),
        "network_out_bytes": sum(sample.network_out_bytes for sample in samples),
    }


def _average(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0.000")
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        PERCENT_QUANTUM, rounding=ROUND_HALF_UP
    )


def _contains_sample(db: Session, scope: CostScope, window: ResourceWindow) -> bool:
    filters: list[Any] = [CostRecord.usage_date.between(window.start, window.end)]
    if scope.provider:
        filters.append(CostRecord.provider == scope.provider)
    if scope.service:
        filters.append(CostRecord.service == scope.service)
    if scope.region:
        filters.append(CostRecord.region == scope.region)
    if scope.environment:
        filters.append(CostRecord.environment == scope.environment)
    if scope.project:
        filters.append(CostRecord.project == scope.project)
    sources = set(
        db.scalars(
            select(ImportRecord.source)
            .join(CostRecord, CostRecord.import_id == ImportRecord.id)
            .where(*filters)
            .distinct()
        )
    )
    return "sample" in sources


def _notes(total: int, window: ResourceWindow) -> list[str]:
    return [
        "Utilization is aggregated only for resources that also appear in billing; "
        "billing rows without utilization samples are not listed here.",
        "idle_candidate and rightsize_candidate are threshold pre-checks, not findings. "
        "Run analysis to create evidence-linked findings.",
        f"Window {window.start.isoformat()} to {window.end.isoformat()} "
        f"({window.days} days); {total} resource(s) matched.",
    ]
