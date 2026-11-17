"""spend forecasting runs and daily points

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17

Adds immutable forecast runs and their daily predicted points. Money stays as
scaled ``BIGINT`` micro-units; timestamps remain timezone-aware.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "seasonal_naive",
                "moving_average",
                name="forecastmethod",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "granularity",
            sa.Enum("day", name="forecastgranularity", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("history_start", sa.Date(), nullable=True),
        sa.Column("history_end", sa.Date(), nullable=True),
        sa.Column("horizon_start", sa.Date(), nullable=True),
        sa.Column("horizon_end", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("series_count", sa.Integer(), nullable=False),
        sa.Column("evaluation", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("forecast_runs", schema=None) as batch_op:
        batch_op.create_index("ix_forecast_runs_created_at", ["created_at"], unique=False)

    op.create_table(
        "forecast_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("predicted_cost", sa.BigInteger(), nullable=False),
        sa.Column("lower_bound", sa.BigInteger(), nullable=False),
        sa.Column("upper_bound", sa.BigInteger(), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "seasonal_naive",
                "moving_average",
                name="forecastmethod",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("forecast_points", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_forecast_points_run_id"), ["run_id"], unique=False)
        batch_op.create_index(
            "ix_forecast_points_run_currency_period",
            ["run_id", "currency", "period"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("forecast_points", schema=None) as batch_op:
        batch_op.drop_index("ix_forecast_points_run_currency_period")
        batch_op.drop_index(batch_op.f("ix_forecast_points_run_id"))
    op.drop_table("forecast_points")

    with op.batch_alter_table("forecast_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_forecast_runs_created_at")
    op.drop_table("forecast_runs")
