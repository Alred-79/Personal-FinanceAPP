"""game event substrate (v4 package 01)

Revision ID: f6a7b8c9d0e1
Revises: e4f5a6b7c8d9
Create Date: 2026-06-12

Adds the append-only game-domain event log and its supporting tables, plus the
small set of additive columns packages 01-05 need. Financial-truth tables
(accounts, expenses, income, budgets, goals, rules) are NOT touched.

Migration A — core game tables:
- game_events       — append-only log; rowid is the global order (single
                      writer), (stream, seq) is the per-stream order. DB-level
                      triggers reject UPDATE/DELETE so a future bug can't mutate
                      history.
- projection_meta   — per-projection watermark + rebuild status.
- llm_cache         — cache for LLM flavor output (package 07+ uses it; the
                      table exists now so the seam is in place).

Migration B — additive columns on existing tables (only those used by 01-05):
- users.game_mode           — 'off' | 'ambient' | 'full' (package 02).
- transactions.worth_it      — modelled here as expenses.worth_it /
                               income.worth_it since this schema splits
                               transactions into expenses + income.
- category_settings          — categories are strings on expenses/income (no
                               categories table), so essentials live in a side
                               table keyed by category name.

Plaid sync bookkeeping (tokens.cursor) already exists, so no sync_cursor column
is added. Liabilities are deliberately deferred to package 06.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str]] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Migration A: core game tables --------------------------------------
    op.create_table(
        "game_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("v", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column(
            "caused_by",
            sa.Integer(),
            sa.ForeignKey("game_events.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("stream", "seq", name="uq_game_events_stream_seq"),
        sa.UniqueConstraint("idempotency_key", name="uq_game_events_idem"),
    )
    op.create_index("ix_game_events_stream", "game_events", ["stream"])
    op.create_index("ix_game_events_type", "game_events", ["type"])

    op.create_table(
        "projection_meta",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("last_event_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rebuilt_at", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="live"),
    )

    op.create_table(
        "llm_cache",
        sa.Column("cache_key", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=True),
    )

    # Append-only enforcement at the DB layer (guardrail against future bugs).
    # These mirror the SQLAlchemy after_create hook so a create_all DB (tests)
    # gets the same guard.
    op.execute(
        "CREATE TRIGGER game_events_no_update BEFORE UPDATE ON game_events "
        "BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER game_events_no_delete BEFORE DELETE ON game_events "
        "BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END"
    )

    # ---- Migration B: additive columns on existing tables -------------------
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "game_mode",
                sa.String(),
                nullable=False,
                server_default="off",
            )
        )

    # This schema splits "transactions" into expenses + income; add worth_it to
    # both so packages 05/09 can tag either kind. Nullable, no default value.
    with op.batch_alter_table("expenses") as batch:
        batch.add_column(sa.Column("worth_it", sa.String(), nullable=True))
    with op.batch_alter_table("income") as batch:
        batch.add_column(sa.Column("worth_it", sa.String(), nullable=True))

    # Categories are strings (no categories table) → essentials live in a side
    # table keyed by the canonical category name.
    op.create_table(
        "category_settings",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("essential", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_confirmed", sa.Integer(), nullable=False, server_default="0"),
    )
    # Seed the default essential categories. user_confirmed stays 0 — the user
    # hasn't reviewed these yet; they're defaults the engine can override.
    essentials = (
        "Rent",
        "Mortgage",
        "Groceries",
        "Utilities",
        "Medical",
        "Insurance",
        "Childcare",
        "Debt",
    )
    settings_table = sa.table(
        "category_settings",
        sa.column("name", sa.String),
        sa.column("essential", sa.Integer),
        sa.column("user_confirmed", sa.Integer),
    )
    op.bulk_insert(
        settings_table,
        [
            {"name": name, "essential": 1, "user_confirmed": 0}
            for name in essentials
        ],
    )


def downgrade() -> None:
    # Downgrade drops ONLY the new game tables/columns; existing financial-truth
    # tables are never touched.
    op.drop_table("category_settings")
    with op.batch_alter_table("income") as batch:
        batch.drop_column("worth_it")
    with op.batch_alter_table("expenses") as batch:
        batch.drop_column("worth_it")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("game_mode")

    op.execute("DROP TRIGGER IF EXISTS game_events_no_delete")
    op.execute("DROP TRIGGER IF EXISTS game_events_no_update")
    op.drop_table("llm_cache")
    op.drop_table("projection_meta")
    op.drop_index("ix_game_events_type", table_name="game_events")
    op.drop_index("ix_game_events_stream", table_name="game_events")
    op.drop_table("game_events")
