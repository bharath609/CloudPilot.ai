"""AI advisor reports

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17

Stores one immutable, evidence-linked explanation per report. The evidence
column contains only the bounded, redacted package that was eligible to leave the
machine; raw billing files are never stored here.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "advisor_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("ai_used", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("analysis_run_id", sa.Integer(), nullable=True),
        sa.Column("forecast_run_id", sa.Integer(), nullable=True),
        sa.Column("fallback_reason", sa.String(length=64), nullable=True),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["analysis_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"], ["forecast_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("advisor_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_advisor_reports_analysis_run"), ["analysis_run_id"], unique=False
        )
        batch_op.create_index(
            "ix_advisor_reports_created_at", ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_advisor_reports_forecast_run"), ["forecast_run_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("advisor_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_advisor_reports_forecast_run"))
        batch_op.drop_index("ix_advisor_reports_created_at")
        batch_op.drop_index(batch_op.f("ix_advisor_reports_analysis_run"))
    op.drop_table("advisor_reports")
