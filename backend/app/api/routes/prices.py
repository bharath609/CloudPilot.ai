"""Read-only endpoints for the sourced price catalogue."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import NotFoundError
from app.db.models import PriceEntry
from app.schemas.prices import PriceEntryOut, PriceListResponse

router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("", response_model=PriceListResponse, summary="List sourced catalogue prices")
def list_prices(
    provider: str | None = Query(None),
    sku: str | None = Query(None),
    region: str | None = Query(None),
    currency: str | None = Query(None, pattern=r"^[A-Za-z]{3}$"),
    synthetic: bool | None = Query(None, description="Filter synthetic demo entries"),
    effective_on: date | None = Query(None, description="Only prices effective on this date"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PriceListResponse:
    filters: list[Any] = []
    if provider:
        filters.append(PriceEntry.provider == provider)
    if sku:
        filters.append(PriceEntry.sku == sku)
    if region:
        filters.append(PriceEntry.region == region)
    if currency:
        filters.append(PriceEntry.currency == currency.upper())
    if synthetic is not None:
        filters.append(PriceEntry.is_synthetic.is_(synthetic))
    if effective_on is not None:
        filters.append(PriceEntry.effective_from <= effective_on)
        filters.append(
            (PriceEntry.effective_to.is_(None)) | (PriceEntry.effective_to >= effective_on)
        )

    total = int(db.scalar(select(func.count()).select_from(PriceEntry).where(*filters)) or 0)
    synthetic_count = int(
        db.scalar(
            select(func.count())
            .select_from(PriceEntry)
            .where(*filters, PriceEntry.is_synthetic.is_(True))
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(PriceEntry)
            .where(*filters)
            .order_by(PriceEntry.provider, PriceEntry.sku, PriceEntry.effective_from.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    notes = [
        "Prices are sourced from the local catalogue file; CloudPilot does not fetch live cloud prices.",
        "Rows marked is_synthetic=true are fabricated demo data and are not vendor prices or quotes.",
    ]
    if synthetic_count:
        notes.append(f"{synthetic_count} of {total} matching price entries are synthetic.")
    if not rows:
        notes.append("No price entries match the requested filters; no price was inferred.")
    return PriceListResponse(
        items=[PriceEntryOut.model_validate(row) for row in rows],
        total=total,
        synthetic_count=synthetic_count,
        notes=notes,
    )


@router.get("/{price_id}", response_model=PriceEntryOut, summary="One catalogue price with provenance")
def get_price(price_id: int, db: Session = Depends(get_db)) -> PriceEntryOut:
    row = db.get(PriceEntry, price_id)
    if row is None:
        raise NotFoundError(f"Price entry {price_id} was not found.")
    return PriceEntryOut.model_validate(row)
