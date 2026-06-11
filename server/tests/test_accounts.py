"""End to end account tests: ORM migration, cents storage, and atomicity.

Per the roadmap: "Write the rollback test **first**."
These tests use the ``client`` and ``db_session`` fixtures from conftest.py
(in memory SQLite, same engine, FK enforcement on).
"""

from unittest.mock import patch

import pytest
from sqlalchemy import select, func

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    User as UserORM,
)


# ── Helper: sign up and get an auth header ───────────────────────────────────

def _auth_header(client, username="testuser", email="test@example.com"):
    """Sign up a test user and return the Authorization header dict."""
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Test User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    # Signup sets auth cookies; clear them so the returned Bearer header is the
    # sole credential (get_current_user prefers the cookie when both exist).
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _create_account(client, headers, balance=123.45, name="Checking", type_="checking"):
    """Create an account and return its id."""
    resp = client.post(
        "/api/accounts/",
        json={"name": name, "type": type_, "balance": balance},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# Rollback / Atomicity tests (written FIRST per roadmap)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeleteAccountAtomicity:
    """Verify that account deletion is atomic: all or nothing."""

    def test_delete_account_cascades_children(self, client, db_session):
        """Deleting an account removes its child expenses and income rows."""
        headers = _auth_header(client)

        # Create an account
        _create_account(client, headers, balance=100.00)

        # Find the account
        account = db_session.execute(select(AccountORM)).scalar_one()
        acct_id = account.id

        # Add child transactions directly via ORM
        db_session.add(
            ExpenseORM(
                title="Lunch", amount=1500, date="2026-01-15",
                category="Food", account_id=acct_id,
            )
        )
        db_session.add(
            IncomeORM(
                title="Salary", amount=500000, date="2026-01-01",
                category="Work", account_id=acct_id,
            )
        )
        db_session.commit()

        # Verify children exist
        assert db_session.execute(select(func.count()).select_from(ExpenseORM)).scalar() == 1
        assert db_session.execute(select(func.count()).select_from(IncomeORM)).scalar() == 1

        # Delete the account
        resp = client.delete(f"/api/accounts/{acct_id}/", headers=headers)
        assert resp.status_code == 200, resp.text

        # Refresh session to see changes committed by the other session
        db_session.expire_all()

        # All gone
        assert db_session.execute(select(func.count()).select_from(AccountORM)).scalar() == 0
        assert db_session.execute(select(func.count()).select_from(ExpenseORM)).scalar() == 0
        assert db_session.execute(select(func.count()).select_from(IncomeORM)).scalar() == 0

    def test_delete_account_rolls_back_on_error(self, client, db_session):
        """A failure mid delete leaves the account and children intact."""
        headers = _auth_header(client)
        _create_account(client, headers, balance=50.00)

        account = db_session.execute(select(AccountORM)).scalar_one()
        acct_id = account.id

        # Add a child expense
        db_session.add(
            ExpenseORM(
                title="Coffee", amount=450, date="2026-02-01",
                category="Food", account_id=acct_id,
            )
        )
        db_session.commit()

        # Monkeypatch Session.flush to raise AFTER the delete is staged.
        # Starlette's TestClient passes through non HTTP exceptions, so we
        # expect the RuntimeError to propagate.
        from sqlalchemy.orm import Session

        original_flush = Session.flush

        def _exploding_flush(self, objects=None):
            if self.deleted:
                raise RuntimeError("Simulated mid delete failure")
            return original_flush(self, objects)

        with patch.object(Session, "flush", _exploding_flush):
            with pytest.raises(RuntimeError, match="Simulated mid delete failure"):
                client.delete(f"/api/accounts/{acct_id}/", headers=headers)

        # Refresh, account and children should still exist (rolled back by get_db)
        db_session.expire_all()
        assert db_session.execute(select(func.count()).select_from(AccountORM)).scalar() == 1
        assert db_session.execute(select(func.count()).select_from(ExpenseORM)).scalar() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Cents storage tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCentsStorage:
    """Verify money is stored as integer cents in the DB."""

    def test_create_account_stores_cents(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, balance=123.45)

        account = db_session.execute(select(AccountORM)).scalar_one()
        assert account.balance == 12345  # stored as cents

    def test_get_account_returns_dollars(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, balance=99.99)

        accounts = client.get("/api/accounts/", headers=headers).json()
        assert len(accounts) == 1
        assert accounts[0]["balance"] == 99.99  # returned as dollars

    def test_update_account_balance_cents(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, balance=50.00)

        account = db_session.execute(select(AccountORM)).scalar_one()
        acct_id = account.id

        resp = client.put(
            f"/api/accounts/{acct_id}/",
            json={"name": "Savings", "type": "savings", "balance": 200.50},
            headers=headers,
        )
        assert resp.status_code == 200

        db_session.expire_all()
        updated = db_session.execute(
            select(AccountORM).where(AccountORM.id == acct_id)
        ).scalar_one()
        assert updated.balance == 20050  # stored as cents
        assert updated.name == "Savings"


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccountCRUD:
    """Basic CRUD operations through the API."""

    def test_get_accounts_empty(self, client):
        headers = _auth_header(client)
        resp = client.get("/api/accounts/", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_single_account(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, balance=10.00, name="MyAccount")

        account = db_session.execute(select(AccountORM)).scalar_one()
        resp = client.get(f"/api/accounts/{account.id}/", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "MyAccount"
        assert data["balance"] == 10.00

    def test_get_nonexistent_account_404(self, client):
        headers = _auth_header(client)
        resp = client.get("/api/accounts/9999/", headers=headers)
        assert resp.status_code == 404

    def test_delete_nonexistent_account_404(self, client):
        headers = _auth_header(client)
        resp = client.delete("/api/accounts/9999/", headers=headers)
        assert resp.status_code == 404

    def test_get_account_transactions_returns_both_types(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, balance=500.00)

        account = db_session.execute(select(AccountORM)).scalar_one()
        acct_id = account.id

        # Add expense and income
        db_session.add(
            ExpenseORM(
                title="Groceries", amount=5025, date="2026-03-15",
                category="Food", account_id=acct_id,
            )
        )
        db_session.add(
            IncomeORM(
                title="Freelance", amount=100000, date="2026-03-01",
                category="Work", account_id=acct_id,
            )
        )
        db_session.commit()

        resp = client.get(f"/api/accounts/{acct_id}/transactions/", headers=headers)
        assert resp.status_code == 200

        txns = resp.json()
        assert len(txns) == 2
        types = {t["type"] for t in txns}
        assert types == {"expense", "income"}

        # Amounts returned as dollars
        amounts = {t["title"]: t["amount"] for t in txns}
        assert amounts["Groceries"] == 50.25
        assert amounts["Freelance"] == 1000.00
