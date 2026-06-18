"""WS2: denormalize user_id onto the 6 child tenant tables (for RLS).

Revision ID: c9e3a5b7d1f2
Revises: b8d2f1a4c6e9
Create Date: 2026-06-18

Each child here reaches the user only via a parent FK. RLS policies must filter
on a local ``user_id``, so we denormalize it onto the child (== the parent's) and
backfill from the parent. Mirrors the columns added in server/src/db/models.py
and the app-layer ``_backfill_user_id`` insert hook (which keeps it correct on
future inserts).

Dialect handling:
* Postgres (the RLS target): add the column, backfill, index, FK, and SET NOT NULL
  — all native ALTERs, no table rebuild.
* SQLite: add the column, backfill, and index only. ``add_column``/``create_index``
  need no table rebuild, so the partial unique indexes on expenses/income
  (uq_expense_plaid_txn, …) are untouched. We deliberately skip the FK + NOT NULL
  on SQLite (which WOULD force a batch rebuild): SQLite doesn't enforce RLS, the
  app-layer backfill keeps the column populated, and the create_all schema (the
  test path) already carries the full constraints.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e3a5b7d1f2"
down_revision: Union[str, Sequence[str]] = "b8d2f1a4c6e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (child, parent, fk_column) — child.user_id is backfilled from parent.user_id.
_CHILDREN = [
    ("expenses", "accounts", "account_id"),
    ("income", "accounts", "account_id"),
    ("rule_executions", "rules", "rule_id"),
    ("liability_adjustments", "liabilities", "liability_id"),
    ("import_rows", "import_sessions", "session_id"),
    ("campaign_progress", "campaigns", "campaign_id"),
]


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    for child, parent, fk in _CHILDREN:
        op.add_column(child, sa.Column("user_id", sa.Integer(), nullable=True))
        # Backfill from the parent (correlated subquery; portable to both dialects).
        op.execute(
            f"UPDATE {child} SET user_id = "
            f"(SELECT p.user_id FROM {parent} p WHERE p.id = {child}.{fk})"
        )
        op.create_index(f"ix_{child}_user_id", child, ["user_id"])
        if is_pg:
            # Guard: a NULL here would mean a dangling parent FK — fail loudly
            # rather than silently breaking RLS. (No-op on an empty/fresh DB.)
            op.execute(
                f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {child} WHERE user_id IS NULL) "
                f"THEN RAISE EXCEPTION '{child}.user_id backfill left NULLs'; END IF; END $$"
            )
            op.create_foreign_key(
                f"fk_{child}_user_id",
                child,
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )
            op.alter_column(child, "user_id", nullable=False)


def downgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    for child, _parent, _fk in reversed(_CHILDREN):
        if is_pg:
            op.drop_constraint(f"fk_{child}_user_id", child, type_="foreignkey")
            op.drop_index(f"ix_{child}_user_id", table_name=child)
            op.drop_column(child, "user_id")
        else:
            # SQLite drop_column requires a batch rebuild; batch recreates indexes.
            op.drop_index(f"ix_{child}_user_id", table_name=child)
            with op.batch_alter_table(child) as batch:
                batch.drop_column("user_id")
