"""API contracts for append-only human review decisions.

No authentication exists yet, so ``actor`` is a self-declared label rather than
a verified identity. Decisions never mutate a finding or its savings estimate.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DecisionKind, FindingType, RiskLevel

ActorName = Annotated[str, Field(min_length=1, max_length=80)]
DecisionNote = Annotated[str, Field(max_length=500)]


class DecisionRequest(BaseModel):
    """One human decision. Submitting again appends a newer decision."""

    model_config = ConfigDict(extra="forbid")

    decision: DecisionKind
    actor: ActorName
    note: DecisionNote | None = None


class FindingDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    finding_id: int
    decision: DecisionKind
    actor: str
    note: str | None = None
    created_at: datetime


class DecisionListItem(FindingDecisionOut):
    """A decision with just enough finding context for the audit page."""

    finding_type: FindingType
    resource_id: str
    service: str
    environment: str
    project: str
    currency: str
    risk: RiskLevel
    estimated_monthly_savings: Decimal
    cost_window_start: date
    cost_window_end: date


class DecisionListResponse(BaseModel):
    items: list[DecisionListItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
