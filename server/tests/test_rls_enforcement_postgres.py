"""WS2 — RLS tenant isolation enforced on the REAL application tables.

Complements test_rls_postgres.py (which proves the mechanism on a synthetic
table): here we enable the actual ``{table}_tenant_isolation`` policies on
accounts/expenses/goals, seed cross-tenant data, and prove isolation, JOIN
safety, fail-closed, the pooling-safe transaction scope, and the denormalized
child backfill + integrity — all as a non-superuser ``app_user`` (superusers
bypass RLS, so the production app connects as a restricted role).

Skipped unless TEST_DATABASE_URL points at Postgres.
"""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    User as UserORM,
)
from server.src.db.rls import enable_rls, set_tenant

_PG = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(
    not _PG, reason="RLS is Postgres-only; set TEST_DATABASE_URL to a Postgres URL"
)

_REAL_TABLES = ("accounts", "expenses", "goals")


@pytest.fixture
def rls_real(_engine):
    """Seed two tenants' rows on the real tables, then ENABLE+FORCE RLS on them
    and grant a non-superuser ``app_user`` CRUD. Seeded as the (superuser) owner,
    which bypasses RLS, so the planted cross-tenant data is what the policy must
    then hide. Teardown disables RLS so the shared session schema is left clean.
    """
    # Seed as the (superuser) owner — bypasses RLS, and the ORM applies the
    # client-side column defaults the raw INSERTs would miss. User 1 owns 2
    # accounts, user 2 owns 1 (distinct counts). Explicit ids keep the tests
    # readable; we bump the sequences afterward so app_user's later autoincrement
    # INSERT can't collide on a PK (which would mask the WITH CHECK assertion).
    with Session(_engine) as s:
        s.add_all(
            [
                UserORM(id=1, username="alice", full_name="Alice", email="a@x.com", hashed_password="h"),
                UserORM(id=2, username="bob", full_name="Bob", email="b@x.com", hashed_password="h"),
            ]
        )
        s.flush()
        s.add_all(
            [
                AccountORM(id=1, name="a1", type="checking", user_id=1),
                AccountORM(id=2, name="a2", type="savings", user_id=1),
                AccountORM(id=3, name="b1", type="checking", user_id=2),
            ]
        )
        s.flush()
        s.add_all(
            [
                ExpenseORM(title="e1", amount=100, date="2026-01-01", category="Food", account_id=1, user_id=1),
                ExpenseORM(title="e2", amount=200, date="2026-01-02", category="Food", account_id=3, user_id=2),
            ]
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
        conn.execute(text("SELECT setval('users_id_seq', 2, true)"))
        conn.execute(text("SELECT setval('accounts_id_seq', 3, true)"))
        for tbl in _REAL_TABLES:
            enable_rls(conn, tbl)
            conn.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO app_user")
            )
        conn.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user")
        )
    yield
    with _engine.begin() as conn:
        for tbl in _REAL_TABLES:
            conn.execute(text(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation ON {tbl}"))
            conn.execute(text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY"))


def _as_app(session) -> None:
    session.execute(text("SET LOCAL ROLE app_user"))


def test_tenant_sees_only_their_accounts(_engine, rls_real):
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        assert s.execute(text("SELECT count(*) FROM accounts")).scalar() == 2
        s.rollback()
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 2)
        assert s.execute(text("SELECT count(*) FROM accounts")).scalar() == 1
        s.rollback()


def test_missing_context_fails_closed(_engine, rls_real):
    """No set_tenant → policy matches no rows (never returns everything)."""
    with Session(_engine) as s:
        _as_app(s)
        for tbl in _REAL_TABLES:
            assert s.execute(text(f"SELECT count(*) FROM {tbl}")).scalar() == 0
        s.rollback()


def test_cross_tenant_write_rejected(_engine, rls_real):
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        with pytest.raises(Exception):
            s.execute(
                text(
                    "INSERT INTO accounts (name, type, balance, user_id) "
                    "VALUES ('evil','checking',0,2)"
                )
            )
            s.flush()
        s.rollback()


def test_join_safety_expenses_x_accounts(_engine, rls_real):
    """A JOIN across two tenant tables returns only the caller's rows, even when
    the query references another tenant's account id directly."""
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        n = s.execute(
            text(
                "SELECT count(*) FROM expenses e "
                "JOIN accounts a ON a.id = e.account_id"
            )
        ).scalar()
        assert n == 1  # only e1 (user 1); e2 belongs to user 2 and is invisible
        # Crafted: point at user 2's account id 3 — RLS still hides those rows.
        leaked = s.execute(
            text("SELECT count(*) FROM expenses WHERE account_id = 3")
        ).scalar()
        assert leaked == 0
        s.rollback()


def test_set_local_is_transaction_scoped(_engine, rls_real):
    """Pooling-safety: tenant binding expires at transaction end; a reused
    connection's next transaction starts fails-closed, not inheriting the tenant."""
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        assert s.execute(text("SELECT count(*) FROM accounts")).scalar() == 2
        s.commit()  # ends txn; SET LOCAL role + GUC expire
        _as_app(s)  # re-assume role, but do NOT re-bind tenant
        assert s.execute(text("SELECT count(*) FROM accounts")).scalar() == 0


def test_child_backfill_and_cross_tenant_insert_rejected(_engine, rls_real):
    """The ORM before_insert backfill sets expenses.user_id from the parent account
    under RLS: attaching to your OWN account succeeds (user_id derived = you);
    attaching to ANOTHER tenant's account fails closed (parent invisible → the
    NOT NULL user_id can't be derived)."""
    # Own account (id 2 belongs to user 1): backfill derives user_id = 1.
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        row = ExpenseORM(
            title="ok", amount=50, date="2026-02-01", category="Food", account_id=2
        )
        s.add(row)
        s.flush()
        assert row.user_id == 1
        s.rollback()
    # Another tenant's account (id 3 belongs to user 2) is invisible under tenant 1,
    # so the backfill can't resolve user_id → insert is rejected.
    with Session(_engine) as s:
        _as_app(s)
        set_tenant(s, 1)
        with pytest.raises(Exception):
            s.add(
                ExpenseORM(
                    title="evil",
                    amount=50,
                    date="2026-02-01",
                    category="Food",
                    account_id=3,
                )
            )
            s.flush()
        s.rollback()
