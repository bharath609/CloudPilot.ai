"""SQLAlchemy models for CloudPilot AI."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    ConfidenceLevel,
    DecisionKind,
    FindingStatus,
    FindingType,
    ForecastGranularity,
    ForecastMethod,
    ImportKind,
    ImportStatus,
    RiskLevel,
    ScenarioMethod,
    Severity,
)
from app.core.time import utcnow
from app.db.base import Base, ScaledDecimal, UtcDateTime


def _enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_class]


class ImportRecord(Base):
    """One upload attempt, including rejected ones (append-only audit trail)."""

    __tablename__ = "imports"
    __table_args__ = (Index("ix_imports_kind_created_at", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[ImportKind] = mapped_column(
        Enum(ImportKind, native_enum=False, values_callable=_enum_values, length=16),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, native_enum=False, values_callable=_enum_values, length=24),
        nullable=False,
        index=True,
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currencies: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class CostRecord(Base):
    """Normalized billing row. Money and quantity are exact decimals."""

    __tablename__ = "cost_records"
    __table_args__ = (
        Index("ix_cost_records_provider_date", "provider", "usage_date"),
        Index("ix_cost_records_currency_date", "currency", "usage_date"),
        UniqueConstraint(
            "import_id",
            "usage_date",
            "provider",
            "account_id",
            "service",
            "resource_id",
            "usage_unit",
            "amount",
            name="uq_cost_records_business_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    usage_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    project: Mapped[str] = mapped_column(String(120), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    usage_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    #: Optional provider SKU used to join a sourced catalogue price. Never inferred.
    sku: Mapped[str | None] = mapped_column(String(120), index=True)

    tags: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    raw_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class ResourceMetric(Base):
    """Normalized utilization sample."""

    __tablename__ = "resource_metrics"
    __table_args__ = (
        UniqueConstraint("resource_id", "observed_at", name="uq_metrics_resource_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    resource_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)

    cpu_avg_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(3), nullable=False)
    cpu_p95_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(3), nullable=False)
    memory_avg_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(3), nullable=False)
    memory_p95_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(3), nullable=False)
    network_in_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    network_out_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_used_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(3), nullable=False)
    sample_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class ImportIssue(Base):
    """Row-level or structural validation issue attached to an import."""

    __tablename__ = "import_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column: Mapped[str | None] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, native_enum=False, values_callable=_enum_values, length=8),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class PriceEntry(Base):
    """One sourced unit price for a provider SKU on an effective date range.

    Synthetic demo entries are allowed only when ``is_synthetic`` is true. The
    API and every finding expose that flag so a demo catalogue is never passed
    off as a vendor price list.
    """

    __tablename__ = "price_entries"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "sku",
            "region",
            "currency",
            "usage_unit",
            "effective_from",
            name="uq_price_entries_identity",
        ),
        Index("ix_price_entries_provider_sku", "provider", "sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    service: Mapped[str] = mapped_column(String(80), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    usage_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    replacement_sku: Mapped[str | None] = mapped_column(String(120))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_retrieved_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class AnalysisRun(Base):
    """Immutable record of one deterministic waste-detection run."""

    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    reference_date: Mapped[date | None] = mapped_column(Date)
    cost_window_start: Mapped[date | None] = mapped_column(Date)
    cost_window_end: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rule_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_savings_by_currency: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    uses_synthetic_prices: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class Finding(Base):
    """A deterministic, evidence-backed waste candidate. Never an action."""

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_run_type", "run_id", "finding_type"),
        Index("ix_findings_resource", "resource_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_type: Mapped[FindingType] = mapped_column(
        Enum(FindingType, native_enum=False, values_callable=_enum_values, length=32),
        nullable=False,
    )
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, native_enum=False, values_callable=_enum_values, length=16),
        nullable=False,
        default=FindingStatus.OPEN,
    )

    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    project: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    current_sku: Mapped[str | None] = mapped_column(String(120))
    recommended_sku: Mapped[str | None] = mapped_column(String(120))

    baseline_monthly_cost: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    proposed_monthly_cost: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    estimated_monthly_savings: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    savings_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(3), nullable=False)

    confidence: Mapped[ConfidenceLevel] = mapped_column(
        Enum(ConfidenceLevel, native_enum=False, values_callable=_enum_values, length=16),
        nullable=False,
    )
    risk: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, native_enum=False, values_callable=_enum_values, length=16),
        nullable=False,
    )

    cost_window_start: Mapped[date] = mapped_column(Date, nullable=False)
    cost_window_end: Mapped[date] = mapped_column(Date, nullable=False)
    observation_start: Mapped[datetime | None] = mapped_column(UtcDateTime)
    observation_end: Mapped[datetime | None] = mapped_column(UtcDateTime)
    observation_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    price_source: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    uses_synthetic_prices: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class SavingsScenario(Base):
    """The reproducible arithmetic behind one finding's savings estimate."""

    __tablename__ = "savings_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[ScenarioMethod] = mapped_column(
        Enum(ScenarioMethod, native_enum=False, values_callable=_enum_values, length=32),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    baseline_monthly_cost: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    proposed_monthly_cost: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    estimated_monthly_savings: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class FindingDecision(Base):
    """Append-only record of a human review decision on one finding.

    Findings themselves stay immutable. Recording a decision creates a new row,
    so the full review history is auditable and nothing is silently overwritten.
    There is no authentication yet, so ``actor`` is a self-declared label.
    """

    __tablename__ = "finding_decisions"
    __table_args__ = (
        Index("ix_finding_decisions_finding_id", "finding_id"),
        Index("ix_finding_decisions_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[DecisionKind] = mapped_column(
        Enum(DecisionKind, native_enum=False, values_callable=_enum_values, length=24),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class ForecastRun(Base):
    """Immutable record of one deterministic spend-forecast run."""

    __tablename__ = "forecast_runs"
    __table_args__ = (Index("ix_forecast_runs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    method: Mapped[ForecastMethod] = mapped_column(
        Enum(ForecastMethod, native_enum=False, values_callable=_enum_values, length=32),
        nullable=False,
    )
    granularity: Mapped[ForecastGranularity] = mapped_column(
        Enum(ForecastGranularity, native_enum=False, values_callable=_enum_values, length=8),
        nullable=False,
        default=ForecastGranularity.DAY,
    )
    reference_date: Mapped[date | None] = mapped_column(Date)
    history_start: Mapped[date | None] = mapped_column(Date)
    history_end: Mapped[date | None] = mapped_column(Date)
    horizon_start: Mapped[date | None] = mapped_column(Date)
    horizon_end: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    series_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class ForecastPoint(Base):
    """One daily predicted spend value with an empirical interval."""

    __tablename__ = "forecast_points"
    __table_args__ = (
        Index("ix_forecast_points_run_currency_period", "run_id", "currency", "period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    predicted_cost: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    lower_bound: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    upper_bound: Mapped[Decimal] = mapped_column(ScaledDecimal(6), nullable=False)
    method: Mapped[ForecastMethod] = mapped_column(
        Enum(ForecastMethod, native_enum=False, values_callable=_enum_values, length=32),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class AdvisorReport(Base):
    """One immutable AI-assisted explanation of deterministic evidence.

    The stored evidence is the bounded, redacted package that was eligible to
    leave the machine. An LLM is optional; ``mode`` records whether the output was
    generated by a provider or by the deterministic fallback.
    """

    __tablename__ = "advisor_reports"
    __table_args__ = (
        Index("ix_advisor_reports_created_at", "created_at"),
        Index("ix_advisor_reports_analysis_run", "analysis_run_id"),
        Index("ix_advisor_reports_forecast_run", "forecast_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    ai_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(120))
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    forecast_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="SET NULL"), nullable=True
    )
    fallback_reason: Mapped[str | None] = mapped_column(String(64))
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
