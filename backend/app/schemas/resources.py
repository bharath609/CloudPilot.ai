"""API contracts for the resource health view.

The view is a read-only utilization inventory. ``idle_candidate`` and
``rightsize_candidate`` are pre-checks using the same documented thresholds as
the analysis engine, not findings; only ``/api/analysis/run`` creates findings.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ResourceWindow(BaseModel):
    start: date
    end: date
    days: int


class ResourceHealthItem(BaseModel):
    resource_id: str
    provider: str
    service: str
    region: str
    environment: str
    project: str
    owner: str | None = None
    team: str | None = None

    currency: str | None = None
    window_cost: Decimal | None = None

    observation_start: datetime | None = None
    observation_end: datetime | None = None
    observation_days: int
    sample_count: int

    cpu_avg_pct: Decimal
    cpu_p95_max_pct: Decimal
    memory_avg_pct: Decimal
    memory_p95_max_pct: Decimal
    network_in_bytes: int
    network_out_bytes: int

    idle_candidate: bool
    rightsize_candidate: bool
    warnings: list[str] = Field(default_factory=list)


class ResourceHealthResponse(BaseModel):
    window: ResourceWindow
    items: list[ResourceHealthItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    thresholds: dict[str, str] = Field(default_factory=dict)
    contains_sample_data: bool
    notes: list[str] = Field(default_factory=list)
