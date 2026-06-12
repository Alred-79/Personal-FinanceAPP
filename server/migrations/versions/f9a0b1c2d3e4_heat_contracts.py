"""heat_contracts (v4 package 09)

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-06-12

Adds ``heat_contracts`` — user-composed constraint contracts priced in Heat. The
self-funding sweep flows through the v1 rule engine (propose→confirm); this table
only records the contract + its arm/status. Additive only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str]] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "heat_contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("target_param", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heat_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("arm", sa.String(), nullable=False, server_default="cosmetic"),
        sa.Column("sweep_rule_id", sa.Integer(), nullable=True),
        sa.Column("sweep_paused", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_extended", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp()
        ),
    )
    op.create_index("ix_heat_contracts_user_id", "heat_contracts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_heat_contracts_user_id", table_name="heat_contracts")
    op.drop_table("heat_contracts")
