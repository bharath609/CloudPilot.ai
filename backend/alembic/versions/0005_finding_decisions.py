"""Finding review decisions

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18

Append-only human decisions on findings. Findings and their savings stay
immutable; a decision is a new row so the review history can be audited.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "finding_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("finding_decisions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_finding_decisions_created_at", ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_finding_decisions_finding_id"), ["finding_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("finding_decisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_finding_decisions_finding_id"))
        batch_op.drop_index("ix_finding_decisions_created_at")
    op.drop_table("finding_decisions")
