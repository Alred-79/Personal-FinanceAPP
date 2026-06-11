"""Canonicalize existing category labels.

Normalize-on-write keeps *new* categories on the canonical taxonomy, but rows
imported before that (notably Plaid expenses stored with raw PFC codes like
``FOOD_AND_DRINK``) still carry off-taxonomy labels that never matched budgets
or the UI color map. This one-time data migration rewrites the existing
``category`` values in expenses, income, merchant_categories, and budgets using
the same ``canonicalize_category`` helper the write paths use.

The downgrade is a no-op: the original raw labels can't be reconstructed, and
the canonical labels are valid either way.

Revision ID: c1d2e3f4a5b6
Revises: b8c9d0e1f2a3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from server.src.services.categorization_service import canonicalize_category

revision = "c1d2e3f4a5b6"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Tables whose `category` has no per-row uniqueness constraint: a plain
    # distinct-value rewrite is safe.
    for table in ("expenses", "income", "merchant_categories"):
        rows = conn.execute(
            sa.text(f"SELECT DISTINCT category FROM {table}")
        ).fetchall()
        for (raw,) in rows:
            canon = canonicalize_category(raw)
            if canon != raw:
                conn.execute(
                    sa.text(
                        f"UPDATE {table} SET category = :new WHERE category = :old"
                    ),
                    {"new": canon, "old": raw},
                )

    # Budgets carry a UNIQUE(user_id, category). Rewrite per row, but skip any
    # rewrite that would collide with an existing budget for the same user so
    # the constraint can't be violated mid-migration.
    budget_rows = conn.execute(
        sa.text("SELECT id, user_id, category FROM budgets")
    ).fetchall()
    for bid, uid, raw in budget_rows:
        canon = canonicalize_category(raw)
        if canon == raw:
            continue
        clash = conn.execute(
            sa.text(
                "SELECT 1 FROM budgets "
                "WHERE user_id = :u AND category = :c AND id <> :i"
            ),
            {"u": uid, "c": canon, "i": bid},
        ).first()
        if clash:
            continue
        conn.execute(
            sa.text("UPDATE budgets SET category = :c WHERE id = :i"),
            {"c": canon, "i": bid},
        )


def downgrade() -> None:
    # Lossy: the original raw labels are not recoverable. No-op.
    pass
