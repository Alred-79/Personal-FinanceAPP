"""The MCP audit trail must survive RLS.

``mcp_audit_store.persist`` opens its OWN short-lived session (the vault's read
session always rolls back, so an audit row must not ride it). That session is
therefore outside every request-scoped tenant binding: nothing on the MCP path
sets ``user_id_var``, so the ``after_begin`` safety net in ``db/session.py``
cannot bind it either.

Under ``enable_rls=true`` the ``mcp_audit_log_tenant_isolation`` policy's
``WITH CHECK`` compares ``user_id`` against an unset ``app.user_id`` GUC — which
``NULLIF`` maps to NULL — so the INSERT matches nothing and is rejected. And
because ``persist`` swallows every exception (auditing must never break a read),
the row vanishes with no signal at all: the owner's Agent Vault goes quiet in
exactly the deployment that took security most seriously.

Skipped unless TEST_DATABASE_URL points at Postgres (RLS is Postgres-only).
"""

import os

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from server.src.db.models import User as UserORM
from server.src.db.rls import enable_rls

_PG = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(
    not _PG, reason="RLS is Postgres-only; set TEST_DATABASE_URL to a Postgres URL"
)

_TABLE = "mcp_audit_log"


@pytest.fixture
def rls_audit(_engine):
    """Put the audit table in its production shape: RLS forced, and every
    connection acting as a non-superuser.

    ``FORCE ROW LEVEL SECURITY`` binds the table owner, but a *superuser* still
    bypasses RLS unconditionally — and the test role is one. So we install a
    ``connect`` listener that issues ``SET ROLE app_user`` on each new pooled
    connection, which is what the production app does by connecting under a
    restricted role. This reaches ``persist``'s privately-opened session, which
    no fixture could otherwise instrument.
    """
    with Session(_engine) as s:
        s.add(
            UserORM(
                id=1,
                username="alice",
                full_name="Alice",
                email="a@x.com",
                hashed_password="h",
            )
        )
        s.commit()

    with _engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS "
                "(SELECT FROM pg_roles WHERE rolname='app_user') "
                "THEN CREATE ROLE app_user NOSUPERUSER NOLOGIN; END IF; END $$"
            )
        )
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app_user"))
        enable_rls(conn, _TABLE)
        conn.execute(text(f"GRANT SELECT, INSERT ON {_TABLE} TO app_user"))
        conn.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user")
        )

    def _become_app_user(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("SET ROLE app_user")
        cur.close()

    event.listen(_engine, "connect", _become_app_user)
    _engine.dispose()  # force fresh connections so the listener actually fires

    yield

    event.remove(_engine, "connect", _become_app_user)
    _engine.dispose()  # drop the role-bound connections before teardown DDL
    with _engine.begin() as conn:
        conn.execute(text(f"DROP POLICY IF EXISTS {_TABLE}_tenant_isolation ON {_TABLE}"))
        conn.execute(text(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY"))
        conn.execute(text(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY"))


def _count_as_owner(engine) -> int:
    """Count rows with RLS out of the way (``RESET ROLE`` restores the superuser
    session role), so the assertion measures what was WRITTEN, not what the
    policy lets app_user read back."""
    with engine.connect() as conn:
        conn.execute(text("RESET ROLE"))
        return conn.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar()


def test_audit_row_persists_under_rls(_engine, rls_audit):
    """An allowed MCP read must leave an audit row even when RLS is enforced."""
    from server.src.services.mcp_audit_store import persist

    persist(
        user_id=1,
        key_id=7,
        resource="read:accounts",
        decision="allow",
        latency_ms=12.5,
        params_hash="deadbeefcafe0000",
    )

    assert _count_as_owner(_engine) == 1


def test_audit_denial_persists_under_rls(_engine, rls_audit):
    """Denials are the rows an owner most needs; they must survive RLS too."""
    from server.src.services.mcp_audit_store import persist

    persist(
        user_id=1,
        key_id=7,
        resource="auth",
        decision="deny:missing_scope",
    )

    assert _count_as_owner(_engine) == 1
