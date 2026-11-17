"""Pure data structures shared by parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.enums import Severity


@dataclass(frozen=True, slots=True)
class FieldIssue:
    code: str
    message: str
    row_number: int = 0
    column: str | None = None
    severity: Severity = Severity.ERROR
    raw_value: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR


@dataclass(slots=True)
class CsvRow:
    number: int
    values: dict[str, str]
    raw: dict[str, str]
    malformed: bool = False


@dataclass(slots=True)
class ParsedCsv:
    headers: list[str]
    rows: list[CsvRow]
    issues: list[FieldIssue] = field(default_factory=list)
    blank_rows: int = 0


@dataclass(slots=True)
class CostDraft:
    row_number: int
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
    raw: dict[str, str]
    sku: str | None = None


@dataclass(slots=True)
class MetricDraft:
    row_number: int
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


@dataclass(slots=True)
class ValidationOutcome:
    """Common result of validating one file."""

    drafts: list[CostDraft] | list[MetricDraft]
    issues: list[FieldIssue]
    row_count: int
    rejected_rows: int
    currencies: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.is_error)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if not issue.is_error)
