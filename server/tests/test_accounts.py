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


# ═══════════════════════════════════════════════════════════════════════════════
# Step 06: money correctness — atomic balances + guarded, recorded transfers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_account(client, headers, name, balance):
    resp = client.post(
        "/api/accounts/",
        json={"name": name, "type": "checking", "balance": balance},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


class TestAtomicBalanceUpdates:
    def test_balance_update_is_atomic(self, client, db_session):
        """Two sequential transaction creates against the same account net to the
        correct sum — proving an issued ``balance = balance + delta`` UPDATE, not
        a stale read-modify-write."""
        headers = _auth_header(client)
        acct = _make_account(client, headers, "Checking", 100.00)

        # +$25 income then -$10 expense ⇒ 100 + 25 - 10 = 115.
        client.post(
            "/api/income/",
            json={
                "title": "Gig", "amount": 25.00, "date": "2026-03-01",
                "category": "Work", "account_id": acct,
            },
            headers=headers,
        )
        client.post(
            "/api/expenses/",
            json={
                "title": "Lunch", "amount": 10.00, "date": "2026-03-02",
                "category": "Food", "account_id": acct,
            },
            headers=headers,
        )

        row = db_session.execute(
            select(AccountORM).where(AccountORM.id == acct)
        ).scalar_one()
        db_session.refresh(row)
        assert row.balance == 11500  # $115.00 in cents

    def test_create_then_delete_restores_balance(self, client, db_session):
        headers = _auth_header(client, "atomic2", "atomic2@example.com")
        acct = _make_account(client, headers, "Checking", 100.00)
        client.post(
            "/api/expenses/",
            json={
                "title": "Lunch", "amount": 30.00, "date": "2026-03-02",
                "category": "Food", "account_id": acct,
            },
            headers=headers,
        )
        # Balance dropped to $70.
        row = db_session.execute(
            select(AccountORM).where(AccountORM.id == acct)
        ).scalar_one()
        db_session.refresh(row)
        assert row.balance == 7000

        exp = db_session.execute(select(ExpenseORM)).scalar_one()
        resp = client.delete(f"/api/expenses/{exp.id}/", headers=headers)
        assert resp.status_code == 200, resp.text
        db_session.refresh(row)
        assert row.balance == 10000  # reversed back to $100


class TestAccountNameUniqueness:
    def test_duplicate_name_rejected_with_409(self, client):
        """Two accounts with the same name under one user are refused (the
        UNIQUE(user_id, name) constraint), with a clean 409 rather than a 500."""
        headers = _auth_header(client, "dup", "dup@example.com")
        _make_account(client, headers, "Checking", 100.00)

        resp = client.post(
            "/api/accounts/",
            json={"name": "Checking", "type": "checking", "balance": 5.00},
            headers=headers,
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    def test_same_name_allowed_for_different_users(self, client):
        """The constraint is per-user: two different users may both have a
        'Checking' account."""
        h1 = _auth_header(client, "userA", "a@example.com")
        h2 = _auth_header(client, "userB", "b@example.com")
        _make_account(client, h1, "Checking", 100.00)
        resp = client.post(
            "/api/accounts/",
            json={"name": "Checking", "type": "checking", "balance": 1.00},
            headers=h2,
        )
        assert resp.status_code == 200, resp.text


class TestTransfers:
    def test_transfer_rejects_overdraft(self, client, db_session):
        """Transfer more than the source holds → 422 and NO balance change on
        either account (the guard + decrement are one atomic statement)."""
        headers = _auth_header(client, "ovr", "ovr@example.com")
        a = _make_account(client, headers, "Checking", 50.00)
        b = _make_account(client, headers, "Savings", 0.00)

        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": b, "amount": 120.00},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "insufficient" in resp.json()["detail"].lower()

        rows = {
            r.id: r.balance
            for r in db_session.execute(select(AccountORM)).scalars().all()
        }
        assert rows[a] == 5000  # unchanged
        assert rows[b] == 0  # unchanged

    def test_transfer_writes_ledger_and_note(self, client, db_session):
        """A transfer produces ledger record(s) carrying the note; the visible
        transactions reconcile with the new balances."""
        headers = _auth_header(client, "led", "led@example.com")
        a = _make_account(client, headers, "Checking", 300.00)
        b = _make_account(client, headers, "Savings", 50.00)

        resp = client.post(
            "/api/accounts/transfer/",
            json={
                "from_account_id": a,
                "to_account_id": b,
                "amount": 120.00,
                "note": "rent split",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["from"]["balance"] == 180.00
        assert body["to"]["balance"] == 170.00
        assert body["note"] == "rent split"

        # An Expense on the source and an Income on the destination, both carrying
        # the note and tagged category "Transfer".
        exp = db_session.execute(
            select(ExpenseORM).where(ExpenseORM.account_id == a)
        ).scalar_one()
        inc = db_session.execute(
            select(IncomeORM).where(IncomeORM.account_id == b)
        ).scalar_one()
        assert exp.title == "rent split"
        assert inc.title == "rent split"
        assert exp.category == "Transfer"
        assert inc.category == "Transfer"
        assert exp.amount == 12000
        assert inc.amount == 12000

        # Reconciliation: source starting balance − ledger expense == new balance;
        # destination starting balance + ledger income == new balance.
        a_row = db_session.execute(
            select(AccountORM).where(AccountORM.id == a)
        ).scalar_one()
        b_row = db_session.execute(
            select(AccountORM).where(AccountORM.id == b)
        ).scalar_one()
        db_session.refresh(a_row)
        db_session.refresh(b_row)
        assert 30000 - exp.amount == a_row.balance
        assert 5000 + inc.amount == b_row.balance

    def test_transfer_exact_balance_allowed(self, client, db_session):
        headers = _auth_header(client, "exact", "exact@example.com")
        a = _make_account(client, headers, "Checking", 100.00)
        b = _make_account(client, headers, "Savings", 0.00)
        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": b, "amount": 100.00},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["from"]["balance"] == 0.00
        assert resp.json()["to"]["balance"] == 100.00

    def test_transfer_same_account_422(self, client):
        headers = _auth_header(client, "same", "same@example.com")
        a = _make_account(client, headers, "Checking", 100.00)
        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": a, "amount": 5.00},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_transfer_plaid_account_422(self, client, db_session):
        """The Plaid guard refuses a Plaid-synced source.

        Step 08 de-name-keyed the guard onto ``Account.plaid_account_id`` with a
        name→Token fallback. This case exercises the FALLBACK (a Token with a
        matching name, account has no plaid_account_id) so an un-migrated link is
        still detected."""
        headers = _auth_header(client, "plaidx", "plaidx@example.com")
        a = _make_account(client, headers, "Plaid Checking", 100.00)
        b = _make_account(client, headers, "Cash", 0.00)

        from server.src.db.models import Token, User

        user = db_session.query(User).filter_by(username="plaidx").one()
        db_session.add(Token(user_id=user.id, name="Plaid Checking", key="tok"))
        db_session.commit()

        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": b, "amount": 5.00},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "synced" in resp.json()["detail"]

    def test_transfer_renamed_plaid_account_422(self, client, db_session):
        """A *renamed* Plaid account is still refused (id-keyed guard).

        Pins the Step 08 de-name-keying: the account carries plaid_account_id, so
        even though its name no longer matches any Token, the guard refuses it.
        The OLD name-keyed guard would have mis-classified this as manual and let
        a transfer double-count on the next sync."""
        from server.src.db.models import Account as AccountORM, User

        headers = _auth_header(client, "renamed", "renamed@example.com")
        b = _make_account(client, headers, "Cash", 0.00)

        user = db_session.query(User).filter_by(username="renamed").one()
        # A Plaid-synced account whose name matches NO token (it was renamed),
        # linked instead by plaid_account_id.
        synced = AccountORM(
            name="My Renamed Bank",
            type="depository",
            balance=10000,
            plaid_account_id="plaid_acct_renamed",
            user_id=user.id,
        )
        db_session.add(synced)
        db_session.commit()

        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": synced.id, "to_account_id": b, "amount": 5.00},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "synced" in resp.json()["detail"]


class TestBulkAccountTransactions:
    """GET /accounts/all/transactions/ — every account's txns in one call (N+1 fix)."""

    def test_returns_transactions_grouped_by_account(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, name="A", balance=100.00)
        _create_account(client, headers, name="B", balance=200.00)
        accts = db_session.execute(select(AccountORM)).scalars().all()
        a, b = accts[0], accts[1]
        db_session.add_all([
            ExpenseORM(title="Lunch", amount=1500, date="2026-01-15",
                       category="Food", account_id=a.id),
            IncomeORM(title="Pay", amount=500000, date="2026-01-01",
                      category="Work", account_id=a.id),
            ExpenseORM(title="Gas", amount=4000, date="2026-01-20",
                       category="Auto", account_id=b.id),
        ])
        db_session.commit()

        resp = client.get("/api/accounts/all/transactions/", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Keyed by account id (JSON object keys are strings).
        assert {t["title"] for t in body[str(a.id)]} == {"Lunch", "Pay"}
        assert [t["title"] for t in body[str(b.id)]] == ["Gas"]

    def test_empty_account_present_with_empty_list(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, name="Solo", balance=10.00)
        acct = db_session.execute(select(AccountORM)).scalar_one()
        resp = client.get("/api/accounts/all/transactions/", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {str(acct.id): []}

    def test_does_not_leak_other_users_transactions(self, client, db_session):
        headers = _auth_header(client)
        _create_account(client, headers, name="Mine", balance=10.00)
        mine = db_session.execute(select(AccountORM)).scalar_one()
        db_session.add(ExpenseORM(title="Mine-tx", amount=100, date="2026-01-01",
                                  category="X", account_id=mine.id))
        db_session.commit()

        other = _auth_header(client, username="other2", email="other2@x.com")
        resp = client.get("/api/accounts/all/transactions/", headers=other)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {}  # other user owns no accounts here
