"""liabilities + adjustments (v4 package 06 — debt boss)

Revision ID: c6d7e8f9a0b1
Revises: f6a7b8c9d0e1
Create Date: 2026-06-12

Adds the ``liabilities`` table (one debt = one boss) and ``liability_adjustments``
(manual balance reconciliations). These are the one financial-truth-adjacent
tables game code may write — but only via ``liability_service``, never from a
fold. Additive only; no existing table is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str]] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "liabilities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="credit_card"),
        sa.Column("principal_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("apr_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "minimum_payment_cents", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("due_day", sa.Integer(), nullable=True),
        sa.Column(
            "linked_account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("linked_plaid_account", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("is_active_boss", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ordering_choice", sa.String(), nullable=True),
        sa.Column(
            "opened_at", sa.DateTime(), server_default=sa.func.current_timestamp()
        ),
        sa.Column("defeated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_liabilities_user_id", "liabilities", ["user_id"])

    op.create_table(
        "liability_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "liability_id",
            sa.Integer(),
            sa.ForeignKey("liabilities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delta_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp()
        ),
    )


def downgrade() -> None:
    op.drop_table("liability_adjustments")
    op.drop_index("ix_liabilities_user_id", table_name="liabilities")
    op.drop_table("liabilities")
