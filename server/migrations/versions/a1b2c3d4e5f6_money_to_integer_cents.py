"""money to integer cents

Revision ID: a1b2c3d4e5f6
Revises: e9a775ab9d6c
Create Date: 2026-05-30 19:23:00.000000

Convert all money columns from Float (REAL) to Integer cents:
  - accounts.balance
  - expenses.amount
  - income.amount
  - goals.amount
  - goals.progress

Data is backfilled with ``ROUND(value * 100)`` before the column type change.
SQLite requires batch mode for ALTER COLUMN (already configured in env.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str]] = "e9a775ab9d6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Column specs for each table ──────────────────────────────────────────────
# (table_name, column_name, has_default, default_value)
_MONEY_COLUMNS = [
    ("accounts", "balance", True, 0),
    ("expenses", "amount", False, None),
    ("income", "amount", False, None),
    ("goals", "amount", False, None),
    ("goals", "progress", True, 0),
]


def upgrade() -> None:
    """Convert dollar floats → integer cents."""
    conn = op.get_bind()

    # 1. Backfill: multiply existing values by 100 and round to int
    for table, col, _has_default, _default in _MONEY_COLUMNS:
        conn.execute(
            sa.text(
                f"UPDATE {table} SET {col} = CAST(ROUND({col} * 100) AS INTEGER)"
            )
        )

    # 2. Alter column types from Float → Integer (batch mode for SQLite)
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column(
            "balance",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default=sa.text("0.0"),
            server_default=sa.text("0"),
        )

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    with op.batch_alter_table("income") as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    with op.batch_alter_table("goals") as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "progress",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=True,
            existing_server_default=sa.text("0"),
            server_default=sa.text("0"),
        )


def downgrade() -> None:
    """Reverse: integer cents → dollar floats."""
    # 1. Alter column types back to Float
    with op.batch_alter_table("goals") as batch_op:
        batch_op.alter_column(
            "progress",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=True,
            server_default=sa.text("0"),
        )
        batch_op.alter_column(
            "amount",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
        )

    with op.batch_alter_table("income") as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
        )

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
        )

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column(
            "balance",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            server_default=sa.text("0.0"),
        )

    # 2. Convert cents back to dollars
    conn = op.get_bind()
    for table, col, _has_default, _default in _MONEY_COLUMNS:
        conn.execute(
            sa.text(
                f"UPDATE {table} SET {col} = CAST({col} AS REAL) / 100.0"
            )
        )
