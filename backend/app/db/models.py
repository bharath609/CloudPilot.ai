"""SQLAlchemy models for Milestone 1."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ImportKind, ImportStatus, Severity
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
