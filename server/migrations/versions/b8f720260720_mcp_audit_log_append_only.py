"""Agent Vault — make mcp_audit_log append-only at the database

Revision ID: b8f720260720
Revises: b3c1d9f2a4e6
Create Date: 2026-07-20

The table was documented as "append-only" from the day it landed, but nothing
enforced it: no triggers in models.py, none in the a7e920260619 migration that
created it. ``game_events`` had real SQLite + Postgres trigger pairs the whole
time — the audit trail simply never got the same treatment. This closes that
gap, so the one table whose purpose is to be trusted after the fact is protected
by a database control rather than a comment.

BEFORE UPDATE and BEFORE DELETE both abort unconditionally. The threat is
concrete: rewriting a recorded ``deny:...`` into ``allow``, or deleting the
record of a read that happened.

Mirrors the create_all listeners in models.py so a migrated DB and a
``Base.metadata.create_all`` DB (the test suite) end up identical. Idempotent —
re-running is a no-op on both dialects.

NOTE on the FK: ``user_id`` is ON DELETE CASCADE, so after this migration a user
row cannot be deleted while it has audit rows. That is deliberate and matches
game_events; there is no account-deletion path today, and a future one must drop
these triggers first. ``TRUNCATE`` bypasses row-level triggers, so the Postgres
test teardown is unaffected.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b8f720260720"
down_revision = "b3c1d9f2a4e6"
branch_labels = None
depends_on = None

_TABLE = "mcp_audit_log"


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    # The table is created by a7e920260619, but that migration self-skips when the
    # table already exists, so don't assume it ran here either.
    if not _has_table(bind, _TABLE):
        return

    if bind.dialect.name == "postgresql":
        op.execute(
            f"CREATE OR REPLACE FUNCTION {_TABLE}_append_only() RETURNS trigger AS $$ "
            f"BEGIN RAISE EXCEPTION '{_TABLE} is append-only'; END; $$ LANGUAGE plpgsql"
        )
        for evt in ("update", "delete"):
            # Postgres has no CREATE TRIGGER IF NOT EXISTS; drop first for idempotency.
            op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_no_{evt} ON {_TABLE}")
            op.execute(
                f"CREATE TRIGGER {_TABLE}_no_{evt} BEFORE {evt.upper()} ON {_TABLE} "
                f"FOR EACH ROW EXECUTE FUNCTION {_TABLE}_append_only()"
            )
    elif bind.dialect.name == "sqlite":
        for evt in ("update", "delete"):
            op.execute(
                f"CREATE TRIGGER IF NOT EXISTS {_TABLE}_no_{evt} "
                f"BEFORE {evt.upper()} ON {_TABLE} "
                f"BEGIN SELECT RAISE(ABORT, '{_TABLE} is append-only'); END"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return

    if bind.dialect.name == "postgresql":
        for evt in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_no_{evt} ON {_TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {_TABLE}_append_only()")
    elif bind.dialect.name == "sqlite":
        for evt in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_no_{evt}")
