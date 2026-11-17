"""API contracts for the evidence-bound AI advisor.

The advisor output is deliberately narrow: prose, IDs and risk. It cannot carry
new monetary values; those always come from the deterministic evidence package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RiskLevel

EvidenceId = Annotated[
    str,
    Field(pattern=r"^(cost|metric|price|import|forecast|finding)-\d+$", max_length=40),
]
FindingId = Annotated[str, Field(pattern=r"^finding-\d+$", max_length=40)]
ShortText = Annotated[str, Field(min_length=1, max_length=400)]
MediumText = Annotated[str, Field(min_length=1, max_length=1200)]


class AdvisorFindingOut(BaseModel):
    """One prioritized finding. All numbers must already exist in the evidence."""

    model_config = ConfigDict(extra="forbid")

    finding_id: FindingId
    explanation: MediumText
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=40)
    assumptions: list[ShortText] = Field(min_length=1, max_length=10)
    risk: RiskLevel
    recommended_next_step: ShortText


class AdvisorOutputOut(BaseModel):
    """The exact structured output allowed from the model or the fallback."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: Annotated[str, Field(min_length=1, max_length=2000)]
    priority_findings: list[AdvisorFindingOut] = Field(default_factory=list, max_length=20)
    unknowns: list[ShortText] = Field(default_factory=list, max_length=20)
    human_review_required: Literal[True]


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_run_id: int | None = Field(default=None, ge=1)
    forecast_run_id: int | None = Field(default=None, ge=1)
    include_forecast: bool = True


class AdvisorReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    mode: str
    ai_used: bool
    provider: str | None = None
    model: str | None = None
    analysis_run_id: int | None = None
    forecast_run_id: int | None = None
    fallback_reason: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    evidence_sha256: str
    attempts: int
    latency_ms: int
    duration_ms: int
    created_at: datetime
    completed_at: datetime | None = None


class AdvisorReportDetail(AdvisorReportSummary):
    output: AdvisorOutputOut
    evidence: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AdvisorReportListResponse(BaseModel):
    items: list[AdvisorReportSummary] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
