"""add budgets and balance_snapshots tables

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7g8h9
Create Date: 2026-05-30 23:30:00.000000

Adds the envelope-budget and net-worth-snapshot tables.

* ``budgets`` — one per-category spending limit per user (cents).
* ``balance_snapshots`` — point-in-time net-worth total per user/date (cents).

Both money columns are integer cents, consistent with the rest of the schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str]] = "c4d5e6f7g8h9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create budgets and balance_snapshots tables."""
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("monthly_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rollover", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "category", name="uq_budget_user_category"),
    )

    op.create_table(
        "balance_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "date", name="uq_snapshot_user_date"),
    )


def downgrade() -> None:
    """Drop budgets and balance_snapshots tables."""
    op.drop_table("balance_snapshots")
    op.drop_table("budgets")
