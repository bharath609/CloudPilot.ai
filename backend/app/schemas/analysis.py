"""API contracts for waste detection and savings scenarios.

Monetary values are exact decimal strings. Every finding states its cost window,
observation window, price source, assumptions and warnings so a reader can
reproduce or reject the estimate.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    ConfidenceLevel,
    FindingStatus,
    FindingType,
    RiskLevel,
    ScenarioMethod,
)
from app.schemas.decisions import FindingDecisionOut


class AnalysisScopeRequest(BaseModel):
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    provider: str | None = None
    account_id: str | None = None
    service: str | None = None
    region: str | None = None
    environment: str | None = None
    project: str | None = None


class SavingsScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    method: ScenarioMethod
    currency: str
    baseline_monthly_cost: Decimal
    proposed_monthly_cost: Decimal
    estimated_monthly_savings: Decimal
    assumptions: list[str] = Field(default_factory=list)


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    finding_type: FindingType
    status: FindingStatus
    provider: str
    account_id: str
    service: str
    resource_id: str
    region: str
    environment: str
    project: str
    currency: str
    current_sku: str | None = None
    recommended_sku: str | None = None
    baseline_monthly_cost: Decimal
    proposed_monthly_cost: Decimal
    estimated_monthly_savings: Decimal
    savings_pct: Decimal
    confidence: ConfidenceLevel
    risk: RiskLevel
    cost_window_start: date
    cost_window_end: date
    observation_start: datetime | None = None
    observation_end: datetime | None = None
    observation_days: int
    sample_count: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    price_source: dict[str, Any] = Field(default_factory=dict)
    uses_synthetic_prices: bool
    created_at: datetime
    scenario: SavingsScenarioOut | None = None
    decision: FindingDecisionOut | None = None


class AnalysisRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    reference_date: date | None = None
    cost_window_start: date | None = None
    cost_window_end: date | None = None
    currency: str | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    rule_config: dict[str, Any] = Field(default_factory=dict)
    finding_count: int
    total_savings_by_currency: dict[str, Decimal] = Field(default_factory=dict)
    uses_synthetic_prices: bool
    notes: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int
    created_at: datetime
    completed_at: datetime | None = None


class AnalysisRunResult(BaseModel):
    run: AnalysisRunSummary
    findings: list[FindingOut] = Field(default_factory=list)


class FindingListResponse(BaseModel):
    run: AnalysisRunSummary | None = None
    items: list[FindingOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
