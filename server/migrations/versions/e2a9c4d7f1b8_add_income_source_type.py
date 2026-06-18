"""add income.source_type (W5 — Freelancer wedge)

Revision ID: e2a9c4d7f1b8
Revises: d1f4a6c8b3e5
Create Date: 2026-06-18 00:00:00.000000

Adds:
- income.source_type — the income row's tax/earnings CHARACTER:
  'w2' | 'self_employment' | 'other' | NULL (unclassified). Nullable and
  user-overridable. Smoothing + the Tax Reserve act ONLY on 'self_employment'.

Backfill policy (guardrail — must not misclassify):
  Each existing income row is classified with the SAME pure heuristic the app
  uses at creation time (``classify_income_source_type``). The heuristic is
  conservative: it only returns 'self_employment' on an explicit 1099/freelance/
  gig signal, and returns NULL when there is no confident signal. Rows that don't
  match any keyword are left NULL (never guessed). A paycheck is never tagged
  self-employment.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2a9c4d7f1b8"
down_revision: Union[str, Sequence[str]] = "d1f4a6c8b3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable column, then conservatively backfill existing rows."""
    with op.batch_alter_table("income") as batch_op:
        batch_op.add_column(sa.Column("source_type", sa.String(), nullable=True))

    # Conservative backfill using the app's own pure heuristic. Pull (id, title,
    # category) for every existing row, classify in Python, and write back ONLY a
    # confident, non-self-employment-guessing result. Rows with no signal stay NULL.
    from server.src.services.categorization_service import (
        classify_income_source_type,
    )

    bind = op.get_bind()
    income = sa.table(
        "income",
        sa.column("id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("category", sa.String),
        sa.column("source_type", sa.String),
    )
    rows = bind.execute(
        sa.select(income.c.id, income.c.title, income.c.category)
    ).fetchall()
    for row_id, title, category in rows:
        guess = classify_income_source_type(title, category)
        if guess is None:
            continue  # never guess — leave NULL
        bind.execute(
            income.update()
            .where(income.c.id == row_id)
            .values(source_type=guess)
        )


def downgrade() -> None:
    """Drop the source_type column."""
    with op.batch_alter_table("income") as batch_op:
        batch_op.drop_column("source_type")
