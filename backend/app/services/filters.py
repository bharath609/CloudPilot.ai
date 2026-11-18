"""Discoverable filter values, data window and freshness.

Read-only. Values are derived from stored rows, so the UI can never offer a
filter that silently returns nothing.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CostRecord, ImportRecord, PriceEntry
from app.schemas.filters import FilterOptions


def filter_options(db: Session) -> FilterOptions:
    window_start = db.scalar(select(func.min(CostRecord.usage_date)))
    window_end = db.scalar(select(func.max(CostRecord.usage_date)))
    day_count = (
        (window_end - window_start).days + 1
        if window_start is not None and window_end is not None
        else None
    )

    last_import = db.scalar(select(ImportRecord).order_by(ImportRecord.id.desc()).limit(1))
    import_count = int(db.scalar(select(func.count()).select_from(ImportRecord)) or 0)
    sample_imports = int(
        db.scalar(
            select(func.count())
            .select_from(ImportRecord)
            .where(ImportRecord.source == "sample")
        )
        or 0
    )
    synthetic_prices = int(
        db.scalar(
            select(func.count()).select_from(PriceEntry).where(PriceEntry.is_synthetic.is_(True))
        )
        or 0
    )

    notes: list[str] = []
    if import_count == 0:
        notes.append("No imports yet. Upload a billing and utilization CSV or run the seed script.")
    if sample_imports:
        notes.append("At least one import came from the synthetic sample seed.")
    if synthetic_prices:
        notes.append("The price catalogue contains synthetic demo prices, not vendor quotes.")

    return FilterOptions(
        window_start=window_start,
        window_end=window_end,
        day_count=day_count,
        currencies=_distinct(db, CostRecord.currency),
        providers=_distinct(db, CostRecord.provider),
        services=_distinct(db, CostRecord.service),
        regions=_distinct(db, CostRecord.region),
        environments=_distinct(db, CostRecord.environment),
        projects=_distinct(db, CostRecord.project),
        accounts=_distinct(db, CostRecord.account_id),
        import_count=import_count,
        last_import_at=last_import.created_at if last_import else None,
        last_import_filename=last_import.filename if last_import else None,
        last_billing_date=window_end,
        contains_sample_data=sample_imports > 0,
        synthetic_price_count=synthetic_prices,
        notes=notes,
    )


def _distinct(db: Session, column: object) -> list[str]:
    rows = db.scalars(select(column).distinct().order_by(column))  # type: ignore[arg-type]
    return [value for value in rows if value]
