"""waste detection, price catalogue and savings scenarios

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17

Adds the optional billing ``sku`` column, the sourced price catalogue and the
deterministic analysis/finding/scenario tables. Money remains scaled ``BIGINT``
micro-units; timestamps remain timezone-aware.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("cost_records", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sku", sa.String(length=120), nullable=True))
        batch_op.create_index(batch_op.f("ix_cost_records_sku"), ["sku"], unique=False)

    op.create_table(
        "price_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("service", sa.String(length=80), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("usage_unit", sa.String(length=32), nullable=False),
        sa.Column("unit_price", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("replacement_sku", sa.String(length=120), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "sku",
            "region",
            "currency",
            "usage_unit",
            "effective_from",
            name="uq_price_entries_identity",
        ),
    )
    with op.batch_alter_table("price_entries", schema=None) as batch_op:
        batch_op.create_index(
            "ix_price_entries_provider_sku", ["provider", "sku"], unique=False
        )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("cost_window_start", sa.Date(), nullable=True),
        sa.Column("cost_window_end", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("rule_config", sa.JSON(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("total_savings_by_currency", sa.JSON(), nullable=False),
        sa.Column("uses_synthetic_prices", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("analysis_runs", schema=None) as batch_op:
        batch_op.create_index("ix_analysis_runs_created_at", ["created_at"], unique=False)

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column(
            "finding_type",
            sa.Enum(
                "idle_resource",
                "over_provisioned",
                name="findingtype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                name="findingstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("service", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("project", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("current_sku", sa.String(length=120), nullable=True),
        sa.Column("recommended_sku", sa.String(length=120), nullable=True),
        sa.Column("baseline_monthly_cost", sa.BigInteger(), nullable=False),
        sa.Column("proposed_monthly_cost", sa.BigInteger(), nullable=False),
        sa.Column("estimated_monthly_savings", sa.BigInteger(), nullable=False),
        sa.Column("savings_pct", sa.BigInteger(), nullable=False),
        sa.Column(
            "confidence",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="confidencelevel",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "risk",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="risklevel",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("cost_window_start", sa.Date(), nullable=False),
        sa.Column("cost_window_end", sa.Date(), nullable=False),
        sa.Column("observation_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_days", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("price_source", sa.JSON(), nullable=False),
        sa.Column("uses_synthetic_prices", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_findings_run_id"), ["run_id"], unique=False)
        batch_op.create_index("ix_findings_resource", ["resource_id"], unique=False)
        batch_op.create_index("ix_findings_run_type", ["run_id", "finding_type"], unique=False)

    op.create_table(
        "savings_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.Integer(), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "stop_resource",
                "rightsize_sku",
                name="scenariomethod",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("baseline_monthly_cost", sa.BigInteger(), nullable=False),
        sa.Column("proposed_monthly_cost", sa.BigInteger(), nullable=False),
        sa.Column("estimated_monthly_savings", sa.BigInteger(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("savings_scenarios", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_savings_scenarios_finding_id"), ["finding_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("savings_scenarios", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_savings_scenarios_finding_id"))
    op.drop_table("savings_scenarios")

    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.drop_index("ix_findings_run_type")
        batch_op.drop_index("ix_findings_resource")
        batch_op.drop_index(batch_op.f("ix_findings_run_id"))
    op.drop_table("findings")

    with op.batch_alter_table("analysis_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_analysis_runs_created_at")
    op.drop_table("analysis_runs")

    with op.batch_alter_table("price_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_price_entries_provider_sku")
    op.drop_table("price_entries")

    with op.batch_alter_table("cost_records", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_cost_records_sku"))
        batch_op.drop_column("sku")
