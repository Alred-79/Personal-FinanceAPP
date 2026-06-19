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


# ── C1: scheduler batch jobs write rows only because they bind the tenant ─────


def test_c1_scheduler_job_write_needs_tenant_binding(_engine):
    """The C1 fix makes each batch job call ``set_tenant(db, user.id)`` per user.
    This proves WHY that's load-bearing under a restricted role: a tenant-table
    write (MetricRollup, as ``run_weekly_rollups`` / ``job_auditor`` do) is
    REJECTED by RLS WITH CHECK when no tenant is bound, and SUCCEEDS once it is.

    The standard suite builds the schema with RLS OFF, so this test force-enables
    RLS on ``metric_rollups`` (+ grants the app role) for its own scope, mirrors
    the binding the jobs perform, and cleans the table/RLS up afterward.
    """
    with _engine.begin() as conn:
        conn.execute(text(
            "DO $$ BEGIN IF NOT EXISTS "
            "(SELECT FROM pg_roles WHERE rolname='app_user') "
            "THEN CREATE ROLE app_user NOSUPERUSER NOLOGIN; END IF; END $$"
        ))
        conn.execute(text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON metric_rollups TO app_user"
        ))
        conn.execute(text(
            "GRANT USAGE, SELECT ON SEQUENCE metric_rollups_id_seq TO app_user"
        ))
        # Seed an owner user (owner bypasses RLS) for the FK + WITH CHECK target.
        conn.execute(text(
            "INSERT INTO users (username, full_name, email, hashed_password, "
            "disabled, s2s_horizon, s2s_include_income, s2s_include_goals, "
            "s2s_buffer, game_mode) VALUES ('c1u','C1','c1@example.com','x',0,"
            "'paycheck',1,1,0,'off')"
        ))
        uid = conn.execute(
            text("SELECT id FROM users WHERE username='c1u'")
        ).scalar_one()
        enable_rls(conn, "metric_rollups")  # ENABLE + FORCE + tenant policy
    try:
        _ins = (
            "INSERT INTO metric_rollups (user_id, week, metric, value, cohort, "
            "created_at) VALUES (:u, '2026-06-14', 'hard_day_action_rate', 1.0, "
            "'', '2026-06-14T00:00:00+00:00')"
        )
        # 1) No tenant bound → WITH CHECK rejects the insert (fail-closed).
        with Session(_engine) as s:
            s.execute(text("SET LOCAL ROLE app_user"))
            with pytest.raises(Exception):
                s.execute(text(_ins), {"u": uid})
                s.flush()
            s.rollback()
        # 2) With the tenant bound (what the job does), the same write succeeds.
        with Session(_engine) as s:
            s.execute(text("SET LOCAL ROLE app_user"))
            set_tenant(s, uid)
            s.execute(text(_ins), {"u": uid})
            got = s.execute(
                text("SELECT count(*) FROM metric_rollups WHERE user_id = :u"),
                {"u": uid},
            ).scalar()
            assert got == 1
            s.rollback()
    finally:
        with _engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE metric_rollups NO FORCE ROW LEVEL SECURITY"
            ))
            conn.execute(text(
                "ALTER TABLE metric_rollups DISABLE ROW LEVEL SECURITY"
            ))
            conn.execute(text(
                "DROP POLICY IF EXISTS metric_rollups_tenant_isolation "
                "ON metric_rollups"
            ))
            conn.execute(text("DELETE FROM users WHERE username='c1u'"))


def test_advisory_lock_is_mutually_exclusive(_engine):
    """L5 — pg_try_advisory_lock (session-level) blocks a second holder until the
    first releases, so two workers can't race a token's cursor across page commits.

    The test engine uses a StaticPool (one shared connection), so a genuine second
    holder needs an INDEPENDENT connection — we open a second engine to the same DB
    (mirroring two real worker processes)."""
    from sqlalchemy import create_engine

    from server.src.db.rls import advisory_unlock, try_advisory_lock

    key = 987654
    # render_as_string(hide_password=False) — str(url) masks the password as ***.
    other = create_engine(_engine.url.render_as_string(hide_password=False))
    try:
        with Session(_engine) as s1, Session(other) as s2:
            assert try_advisory_lock(s1, key) is True
            # A different connection can't take the same key while s1 holds it.
            assert try_advisory_lock(s2, key) is False
            # The lock survives a commit (session-level, not xact-level) — the
            # property L5 relies on for per-page commits.
            s1.commit()
            assert try_advisory_lock(s2, key) is False
            advisory_unlock(s1, key)
            s1.commit()  # flush the unlock to the backend
            # Now the other connection can acquire it.
            assert try_advisory_lock(s2, key) is True
            advisory_unlock(s2, key)
    finally:
        other.dispose()
