"""WS2: enable Row-Level Security policies on every tenant table (Postgres).

Revision ID: d1f4a6c8b3e5
Revises: c9e3a5b7d1f2
Create Date: 2026-06-18

Installs the ``{table}_tenant_isolation`` ENABLE+FORCE RLS policy (keyed on the
``app.user_id`` GUC) on each table in server/src/db/rls.TENANT_TABLES — the same
helper + list the create_all ``after_create`` listener uses, so the two paths
can't drift. ``enable_rls`` is idempotent (DROP POLICY IF EXISTS then CREATE).

Gated on ``settings.enable_rls`` AND Postgres: policies are installed only when
the deployment has opted into RLS. Coherence: a deployment sets ENABLE_RLS=true
in its env, so this migration (run by `alembic upgrade head`) installs the
policies AND the running app's request path sets the tenant on every request —
both turn on together. With ENABLE_RLS=false (default) this is a no-op, and the
SQLite suite is unaffected.

NOTE: enable RLS *before* the first `alembic upgrade head` on a deployment. To
turn it on for an already-migrated DB, `alembic downgrade d1f4a6c8b3e5-1` then
re-upgrade with ENABLE_RLS=true (or call enable_rls() per table out of band).
Migrations must run as a BYPASSRLS / owner role (see .env.example role model).
"""
from typing import Sequence, Union

from alembic import op

from server.src.db.rls import TENANT_TABLES, enable_rls


revision: str = "d1f4a6c8b3e5"
down_revision: Union[str, Sequence[str]] = "c9e3a5b7d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from server.src.settings import settings

    if not settings.enable_rls:
        return
    for table in TENANT_TABLES:
        enable_rls(bind, table)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
