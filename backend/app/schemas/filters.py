"""API contract for discoverable filter values and data freshness."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class FilterOptions(BaseModel):
    window_start: date | None = None
    window_end: date | None = None
    day_count: int | None = None

    currencies: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)

    import_count: int
    last_import_at: datetime | None = None
    last_import_filename: str | None = None
    last_billing_date: date | None = None

    contains_sample_data: bool
    synthetic_price_count: int
    notes: list[str] = Field(default_factory=list)
