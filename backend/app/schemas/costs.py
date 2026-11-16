"""API contracts for spend analytics.

All monetary values are exact ``Decimal`` strings in JSON. Amounts for different
currencies are never added together; totals are always partitioned by ISO code.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.enums import CostDimension, TrendGranularity


class CostWindow(BaseModel):
    """Effective date window used for a query (inclusive)."""

    start: date | None = None
    end: date | None = None
    days: int | None = None


class CurrencyTotal(BaseModel):
    currency: str
    amount: Decimal
    row_count: int


class CostSummary(BaseModel):
    window: CostWindow
    totals: list[CurrencyTotal] = Field(default_factory=list)
    row_count: int
    excluded_duplicate_rows: int
    import_ids: list[int] = Field(default_factory=list)
    import_count: int
    contains_sample_data: bool
    notes: list[str] = Field(default_factory=list)


class BreakdownItem(BaseModel):
    key: str
    currency: str
    amount: Decimal
    row_count: int
    share_pct: Decimal


class CostBreakdown(BaseModel):
    dimension: CostDimension
    window: CostWindow
    currency: str | None = None
    totals: list[CurrencyTotal] = Field(default_factory=list)
    items: list[BreakdownItem] = Field(default_factory=list)
    total_groups: int
    items_truncated: bool
    excluded_duplicate_rows: int
    notes: list[str] = Field(default_factory=list)


class TrendPoint(BaseModel):
    bucket: str
    currency: str
    amount: Decimal
    row_count: int


class CostTrends(BaseModel):
    granularity: TrendGranularity
    window: CostWindow
    currency: str | None = None
    points: list[TrendPoint] = Field(default_factory=list)
    totals: list[CurrencyTotal] = Field(default_factory=list)
    excluded_duplicate_rows: int
    notes: list[str] = Field(default_factory=list)
