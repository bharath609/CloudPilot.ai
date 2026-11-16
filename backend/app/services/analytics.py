"""Deterministic, currency-partitioned spend analytics.

Everything here is SQL + ``Decimal`` arithmetic over the exact scaled-integer
money columns. No floats, no FX conversion and no AI-generated numbers.

De-duplication rule (approved before Milestone 2): a billing row whose business
key already exists from an earlier import is stored for audit but excluded from
every analytic total. The earliest stored row wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.orm import Session

from app.core.enums import CostDimension, TrendGranularity
from app.db.models import CostRecord, ImportRecord
from app.schemas.costs import (
    BreakdownItem,
    CostBreakdown,
    CostSummary,
    CostTrends,
    CostWindow,
    CurrencyTotal,
    TrendPoint,
)

MONEY_SCALE = 6
SHARE_QUANTUM = Decimal("0.001")

#: Must match the business key used by the ingestion validators.
BUSINESS_KEY = (
    CostRecord.usage_date,
    CostRecord.provider,
    CostRecord.account_id,
    CostRecord.service,
    CostRecord.resource_id,
    CostRecord.usage_unit,
    CostRecord.amount,
)

_DIMENSIONS: dict[CostDimension, Any] = {
    CostDimension.SERVICE: CostRecord.service,
    CostDimension.PROJECT: CostRecord.project,
    CostDimension.REGION: CostRecord.region,
    CostDimension.ENVIRONMENT: CostRecord.environment,
    CostDimension.PROVIDER: CostRecord.provider,
    CostDimension.ACCOUNT: CostRecord.account_id,
    CostDimension.RESOURCE: CostRecord.resource_id,
}


@dataclass(frozen=True, slots=True)
class CostScope:
    """Filters shared by every analytics endpoint. Dates are inclusive."""

    start: date | None = None
    end: date | None = None
    currency: str | None = None
    provider: str | None = None
    account_id: str | None = None
    service: str | None = None
    region: str | None = None
    environment: str | None = None
    project: str | None = None


def summarize(db: Session, scope: CostScope) -> CostSummary:
    filters = _filters(scope)
    dedupe = _dedupe_clause(filters)
    window = _window(db, scope, filters)
    excluded = _excluded_duplicates(db, filters, dedupe)

    rows = db.execute(
        select(
            CostRecord.currency,
            func.count(CostRecord.id).label("row_count"),
            func.coalesce(func.sum(cast(CostRecord.amount, BigInteger)), 0).label("micros"),
        )
        .where(*filters, dedupe)
        .group_by(CostRecord.currency)
        .order_by(CostRecord.currency)
    ).all()

    totals = [
        CurrencyTotal(
            currency=row.currency,
            amount=_money(row.micros),
            row_count=int(row.row_count),
        )
        for row in rows
    ]
    import_ids, contains_sample_data = _import_sources(db, filters, dedupe)
    return CostSummary(
        window=window,
        totals=totals,
        row_count=sum(item.row_count for item in totals),
        excluded_duplicate_rows=excluded,
        import_ids=import_ids,
        import_count=len(import_ids),
        contains_sample_data=contains_sample_data,
        notes=_notes(totals, excluded),
    )


def breakdown(
    db: Session,
    scope: CostScope,
    *,
    dimension: CostDimension,
    limit: int,
) -> CostBreakdown:
    filters = _filters(scope)
    dedupe = _dedupe_clause(filters)
    window = _window(db, scope, filters)
    excluded = _excluded_duplicates(db, filters, dedupe)
    column = _DIMENSIONS[dimension]

    rows = db.execute(
        select(
            column.label("key"),
            CostRecord.currency,
            func.count(CostRecord.id).label("row_count"),
            func.coalesce(func.sum(cast(CostRecord.amount, BigInteger)), 0).label("micros"),
        )
        .where(*filters, dedupe)
        .group_by(column, CostRecord.currency)
        .order_by(CostRecord.currency, func.sum(cast(CostRecord.amount, BigInteger)).desc())
    ).all()

    grouped: list[tuple[str, str, Decimal, int]] = [
        (str(row.key), row.currency, _money(row.micros), int(row.row_count)) for row in rows
    ]
    totals_by_currency: dict[str, Decimal] = {}
    counts_by_currency: dict[str, int] = {}
    for _key, currency, amount, row_count in grouped:
        totals_by_currency[currency] = totals_by_currency.get(currency, Decimal(0)) + amount
        counts_by_currency[currency] = counts_by_currency.get(currency, 0) + row_count

    totals = [
        CurrencyTotal(
            currency=currency,
            amount=totals_by_currency[currency],
            row_count=counts_by_currency[currency],
        )
        for currency in sorted(totals_by_currency)
    ]

    items = [
        BreakdownItem(
            key=key,
            currency=currency,
            amount=amount,
            row_count=row_count,
            share_pct=_share(amount, totals_by_currency[currency]),
        )
        for key, currency, amount, row_count in grouped
    ]
    limited = _limit_per_currency(items, limit)
    return CostBreakdown(
        dimension=dimension,
        window=window,
        currency=scope.currency.upper() if scope.currency else None,
        totals=totals,
        items=limited,
        total_groups=len(items),
        items_truncated=len(limited) < len(items),
        excluded_duplicate_rows=excluded,
        notes=_notes(totals, excluded),
    )


def trends(
    db: Session,
    scope: CostScope,
    *,
    granularity: TrendGranularity,
) -> CostTrends:
    filters = _filters(scope)
    dedupe = _dedupe_clause(filters)
    window = _window(db, scope, filters)
    excluded = _excluded_duplicates(db, filters, dedupe)

    rows = db.execute(
        select(
            CostRecord.usage_date,
            CostRecord.currency,
            func.count(CostRecord.id).label("row_count"),
            func.coalesce(func.sum(cast(CostRecord.amount, BigInteger)), 0).label("micros"),
        )
        .where(*filters, dedupe)
        .group_by(CostRecord.usage_date, CostRecord.currency)
        .order_by(CostRecord.usage_date, CostRecord.currency)
    ).all()

    # Roll daily rows up in Python so day/month bucketing stays dialect-neutral.
    buckets: dict[tuple[str, str], tuple[Decimal, int]] = {}
    for row in rows:
        bucket = _bucket(row.usage_date, granularity)
        amount, row_count = buckets.get((bucket, row.currency), (Decimal(0), 0))
        buckets[(bucket, row.currency)] = (amount + _money(row.micros), row_count + int(row.row_count))

    points = [
        TrendPoint(bucket=bucket, currency=currency, amount=amount, row_count=row_count)
        for (bucket, currency), (amount, row_count) in sorted(buckets.items())
    ]

    totals_by_currency: dict[str, Decimal] = {}
    counts_by_currency: dict[str, int] = {}
    for point in points:
        totals_by_currency[point.currency] = totals_by_currency.get(point.currency, Decimal(0)) + point.amount
        counts_by_currency[point.currency] = counts_by_currency.get(point.currency, 0) + point.row_count
    totals = [
        CurrencyTotal(currency=code, amount=totals_by_currency[code], row_count=counts_by_currency[code])
        for code in sorted(totals_by_currency)
    ]

    return CostTrends(
        granularity=granularity,
        window=window,
        currency=scope.currency.upper() if scope.currency else None,
        points=points,
        totals=totals,
        excluded_duplicate_rows=excluded,
        notes=_notes(totals, excluded),
    )


# -- helpers --------------------------------------------------------------
def _filters(scope: CostScope) -> list[Any]:
    filters: list[Any] = []
    if scope.start is not None:
        filters.append(CostRecord.usage_date >= scope.start)
    if scope.end is not None:
        filters.append(CostRecord.usage_date <= scope.end)
    if scope.currency:
        filters.append(CostRecord.currency == scope.currency.upper())
    if scope.provider:
        filters.append(CostRecord.provider == scope.provider)
    if scope.account_id:
        filters.append(CostRecord.account_id == scope.account_id)
    if scope.service:
        filters.append(CostRecord.service == scope.service)
    if scope.region:
        filters.append(CostRecord.region == scope.region)
    if scope.environment:
        filters.append(CostRecord.environment == scope.environment)
    if scope.project:
        filters.append(CostRecord.project == scope.project)
    return filters


def _dedupe_clause(filters: list[Any]) -> Any:
    """Keep the earliest stored row for each business key."""
    keep_first = (
        select(func.min(CostRecord.id))
        .where(*filters)
        .group_by(*BUSINESS_KEY)
        .scalar_subquery()
    )
    return CostRecord.id.in_(keep_first)


def _window(db: Session, scope: CostScope, filters: list[Any]) -> CostWindow:
    data_start, data_end = db.execute(
        select(func.min(CostRecord.usage_date), func.max(CostRecord.usage_date)).where(*filters)
    ).one()
    start = scope.start or data_start
    end = scope.end or data_end
    days = (end - start).days + 1 if start is not None and end is not None else None
    return CostWindow(start=start, end=end, days=days)


def _excluded_duplicates(db: Session, filters: list[Any], dedupe: Any) -> int:
    stored = int(db.scalar(select(func.count(CostRecord.id)).where(*filters)) or 0)
    counted = int(db.scalar(select(func.count(CostRecord.id)).where(*filters, dedupe)) or 0)
    return max(stored - counted, 0)


def _import_sources(db: Session, filters: list[Any], dedupe: Any) -> tuple[list[int], bool]:
    ids = sorted(set(db.scalars(select(CostRecord.import_id).where(*filters, dedupe).distinct())))
    if not ids:
        return [], False
    sources = set(db.scalars(select(ImportRecord.source).where(ImportRecord.id.in_(ids))))
    return ids, "sample" in sources


def _money(micros: int | None) -> Decimal:
    return Decimal(int(micros or 0)).scaleb(-MONEY_SCALE)


def _share(amount: Decimal, total: Decimal) -> Decimal:
    if total == 0:
        return Decimal("0.000")
    return (amount / total * 100).quantize(SHARE_QUANTUM, rounding=ROUND_HALF_UP)


def _limit_per_currency(items: list[BreakdownItem], limit: int) -> list[BreakdownItem]:
    kept: list[BreakdownItem] = []
    per_currency: dict[str, int] = {}
    for item in items:
        count = per_currency.get(item.currency, 0)
        if count >= limit:
            continue
        per_currency[item.currency] = count + 1
        kept.append(item)
    return kept


def _bucket(value: date, granularity: TrendGranularity) -> str:
    if granularity is TrendGranularity.MONTH:
        return f"{value.year:04d}-{value.month:02d}"
    return value.isoformat()


def _notes(totals: list[CurrencyTotal], excluded: int) -> list[str]:
    notes = [
        "Amounts are exact decimals from imported billing rows; no FX conversion is applied.",
        "Rows are de-duplicated by business key; the earliest stored record wins.",
    ]
    if len(totals) > 1:
        notes.append("Multiple currencies are present and reported separately; do not add them together.")
    if excluded:
        notes.append(f"{excluded} overlapping row(s) from later imports were excluded from these totals.")
    if not totals:
        notes.append("No billing rows match the requested filters.")
    return notes
