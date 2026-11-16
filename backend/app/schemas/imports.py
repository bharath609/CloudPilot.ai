"""API contracts for imports and validation results."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ImportKind, ImportStatus, Severity


class ValidationIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    column: str | None = None
    code: str
    severity: Severity
    message: str
    raw_value: str | None = None


class ImportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ImportKind
    filename: str
    status: ImportStatus
    provider: str | None = None
    row_count: int
    accepted_row_count: int
    rejected_row_count: int
    warning_count: int
    currencies: list[str] = Field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    source: str
    content_sha256: str
    created_at: datetime


class ImportResult(ImportSummary):
    """Response returned by an upload, including a preview of issues."""

    stats: dict[str, Any] = Field(default_factory=dict)
    issues: list[ValidationIssueOut] = Field(default_factory=list)
    issues_truncated: bool = False
    message: str


class ImportDetail(ImportSummary):
    content_bytes: int
    stats: dict[str, Any] = Field(default_factory=dict)
    issue_count: int
    error_count: int


class PaginatedImports(BaseModel):
    items: list[ImportSummary]
    total: int
    limit: int
    offset: int


class PaginatedIssues(BaseModel):
    items: list[ValidationIssueOut]
    total: int
    limit: int
    offset: int


class CostRecordPreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_row_number: int
    usage_date: date
    provider: str
    account_id: str
    service: str
    resource_id: str
    region: str
    environment: str
    project: str
    quantity: Decimal
    usage_unit: str
    amount: Decimal
    currency: str
    tags: dict[str, str]


class MetricPreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_row_number: int
    resource_id: str
    observed_at: datetime
    cpu_avg_pct: Decimal
    cpu_p95_pct: Decimal
    memory_avg_pct: Decimal
    memory_p95_pct: Decimal
    network_in_bytes: int
    network_out_bytes: int
    storage_used_pct: Decimal
    sample_window_minutes: int


class ImportRecordsResponse(BaseModel):
    kind: ImportKind
    items: list[CostRecordPreview | MetricPreview]
    total: int
    limit: int
    offset: int
