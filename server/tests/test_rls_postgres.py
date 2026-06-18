"""WS2 — Row-Level Security tenant isolation, validated on a real Postgres.

Skipped unless TEST_DATABASE_URL points at Postgres (RLS is a Postgres-only
feature — SQLite has no equivalent). Proves the mechanism the multi-tenant brief
requires: only the bound tenant's rows are visible, cross-tenant writes are
rejected, an UNSET context fails closed (sees nothing, not everything), and the
binding is transaction-scoped (the pooling-safety property).

NOTE on roles: Postgres SUPERUSERS bypass RLS unconditionally (even with FORCE).
The production app must therefore connect as a NON-superuser role. The test
superuser ``SET LOCAL ROLE``s to a seeded non-superuser ``app_user`` to reproduce
that, which is exactly how a real deployment isolates tenants.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.src.db.rls import enable_rls, set_tenant

_PG = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(
    not _PG, reason="RLS is Postgres-only; set TEST_DATABASE_URL to a Postgres URL"
)


@pytest.fixture
def rls_table(_engine):
    """A tiny RLS-protected tenant table + a non-superuser ``app_user`` role.

    Rows are seeded BEFORE force-RLS (the owner still bypasses until FORCE), so
    the fixture can plant cross-tenant data the policy must then hide.
    """
    with _engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS "
                "(SELECT FROM pg_roles WHERE rolname='app_user') "
                "THEN CREATE ROLE app_user NOSUPERUSER NOLOGIN; END IF; END $$"
            )
        )
        conn.execute(text("DROP TABLE IF EXISTS rls_demo"))
        conn.execute(
            text(
                "CREATE TABLE rls_demo "
                "(id serial PRIMARY KEY, user_id int NOT NULL, label text)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO rls_demo (user_id, label) "
                "VALUES (1,'a1'),(1,'a2'),(2,'b1')"
            )
        )
        enable_rls(conn, "rls_demo")
        conn.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON rls_demo TO app_user")
        )
        conn.execute(
            text("GRANT USAGE, SELECT ON SEQUENCE rls_demo_id_seq TO app_user")
        )
    yield
    with _engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS rls_demo"))


def _as_app(session) -> None:
    """Drop to the non-superuser app role for this transaction (so RLS applies)."""
    session.execute(text("SET LOCAL ROLE app_user"))


def _count(session) -> int:
    return session.execute(text("SELECT count(*) FROM rls_demo")).scalar()


def test_unset_context_sees_nothing(_engine, rls_table):
    """Fail-closed: app role bound, but no app.user_id → policy matches no rows."""
    with Session(_engine) as s:
        _as_app(s)
        assert _count(s) == 0
        s.rollback()


def test_tenant_sees_only_their_rows(_engine, rls_table):
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        assert _count(s) == 2
        s.rollback()
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 2)
        assert _count(s) == 1
        s.rollback()


def test_cross_tenant_write_rejected(_engine, rls_table):
    """WITH CHECK blocks inserting a row owned by a different tenant."""
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        with pytest.raises(Exception):
            s.execute(
                text("INSERT INTO rls_demo (user_id, label) VALUES (2, 'evil')")
            )
            s.flush()
        s.rollback()


def test_set_local_is_transaction_scoped(_engine, rls_table):
    """Pooling-safety: the tenant binding expires at transaction end, so a reused
    connection's next transaction starts with no context (fails closed) — it
    cannot inherit the prior tenant's context."""
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        assert _count(s) == 2
        s.commit()  # ends the transaction; SET LOCAL role + GUC both expire
        _as_app(s)  # re-assume the app role, but DON'T re-bind the tenant
        assert _count(s) == 0  # the prior tenant GUC did not survive → closed
