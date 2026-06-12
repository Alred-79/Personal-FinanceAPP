"""income recurrence + safe-to-spend prefs + birth_year

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-11

v1 Feature 1 + Feature 3 schema:
- income.recurrence            — closes the forecast schema gap (Expense has it, Income didn't)
- users.s2s_horizon            — Safe-to-Spend horizon ('paycheck' | 'month' | 'week')
- users.s2s_include_income     — 0/1: add projected income to the number
- users.s2s_include_goals      — 0/1: subtract goal earmarks + remaining contributions
- users.s2s_buffer             — integer cents held back
- users.birth_year             — nullable; v4 enabler (percentile cohorts), unused by v1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str]] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("income") as batch_op:
        batch_op.add_column(sa.Column("recurrence", sa.String(), nullable=True))

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "s2s_horizon", sa.String(), nullable=False, server_default="paycheck"
            )
        )
        batch_op.add_column(
            sa.Column(
                "s2s_include_income", sa.Integer(), nullable=False, server_default="1"
            )
        )
        batch_op.add_column(
            sa.Column(
                "s2s_include_goals", sa.Integer(), nullable=False, server_default="1"
            )
        )
        batch_op.add_column(
            sa.Column("s2s_buffer", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("birth_year", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("birth_year")
        batch_op.drop_column("s2s_buffer")
        batch_op.drop_column("s2s_include_goals")
        batch_op.drop_column("s2s_include_income")
        batch_op.drop_column("s2s_horizon")

    with op.batch_alter_table("income") as batch_op:
        batch_op.drop_column("recurrence")
