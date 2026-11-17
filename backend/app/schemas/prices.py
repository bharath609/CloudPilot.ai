"""API contracts for the sourced price catalogue."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PriceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    sku: str
    display_name: str
    service: str
    region: str
    usage_unit: str
    unit_price: Decimal
    currency: str
    effective_from: date
    effective_to: date | None = None
    replacement_sku: str | None = None
    is_synthetic: bool
    source_name: str
    source_url: str
    source_retrieved_at: datetime | None = None
    notes: str | None = None


class PriceListResponse(BaseModel):
    items: list[PriceEntryOut] = Field(default_factory=list)
    total: int
    synthetic_count: int
    notes: list[str] = Field(default_factory=list)
