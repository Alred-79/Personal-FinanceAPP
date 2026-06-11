"""Tests for the Plaid cursor based sync rewrite.

Every test mocks ``PlaidClient``, no sandbox or network calls.
The in memory SQLite DB from conftest provides the session and engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Token as TokenORM,
    User as UserORM,
)
from server.src.money import dollars_to_cents
from server.src.models import UserInDB
from server.src.services.plaid_service import PlaidService
from server.src.databridge.plaid_client import SyncResult


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def seed_user(db_session):
    """Create a user and return a UserInDB for service calls."""
    user = UserORM(
        username="plaidtester",
        full_name="Plaid Tester",
        email="plaid@test.com",
        hashed_password="fakehash",
        disabled=0,
    )
    db_session.add(user)
    db_session.flush()
    return UserInDB(
        id=int(user.id),  # type: ignore[arg-type]
        username=str(user.username),
        email=str(user.email),
        full_name=str(user.full_name),
        disabled=False,
        hashed_password=str(user.hashed_password),
    )


@pytest.fixture
def seed_account(db_session, seed_user):
    """Create a linked account + token and return (account_id, token)."""
    token = TokenORM(
        user_id=seed_user.id,
        name="Chase Checking",
        key="access-sandbox-fake",
    )
    db_session.add(token)
    db_session.flush()

    account = AccountORM(
        name="Chase Checking",
        type="depository",
        balance=0,
        user_id=seed_user.id,
    )
    db_session.add(account)
    db_session.flush()
    return account.id, token


def _make_plaid_txn(
    txn_id: str,
    name: str,
    amount: float,
    date: str = "2024-06-15",
    category: list | None = None,
) -> dict:
    """Build a minimal Plaid transaction dict."""
    return {
        "transaction_id": txn_id,
        "name": name,
        "amount": amount,
        "date": date,
        "category": ["Shopping"] if category is None else category,
        "personal_finance_category": None,
    }


# ── Tests ────────────────────────────────────────────────────────────────────


class TestSyncAdded:
    """sync_transactions adding new rows."""

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_added_creates_rows(self, MockPDB, db_session, seed_user, seed_account):
        """Added transactions should insert new Expense/Income rows."""
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[
                _make_plaid_txn("txn_1", "Coffee", 4.50),
                _make_plaid_txn("txn_2", "Grocery Store", 85.00),
                _make_plaid_txn("txn_3", "Paycheck", -2500.00),
            ],
            modified=[],
            removed=[],
            next_cursor="cursor_abc",
        )

        svc = PlaidService(db_session)
        summary = svc.sync_all_tokens(seed_user)
        db_session.flush()

        expenses = db_session.execute(select(ExpenseORM)).scalars().all()
        incomes = db_session.execute(select(IncomeORM)).scalars().all()

        assert len(expenses) == 2
        assert len(incomes) == 1
        assert {e.plaid_transaction_id for e in expenses} == {"txn_1", "txn_2"}
        assert incomes[0].plaid_transaction_id == "txn_3"
        assert incomes[0].amount == dollars_to_cents(2500.00)  # stored positive

        # Cursor should be updated
        db_session.refresh(token)
        assert token.cursor == "cursor_abc"

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_idempotent(self, MockPDB, db_session, seed_user, seed_account):
        """Running sync twice with the same data should NOT create duplicates."""
        account_id, token = seed_account

        txns = [_make_plaid_txn("txn_dup", "Duplicate Purchase", 19.99)]

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=txns, modified=[], removed=[], next_cursor="c1",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        # Second sync with same added list
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=txns, modified=[], removed=[], next_cursor="c2",
        )
        svc2 = PlaidService(db_session)
        svc2.sync_all_tokens(seed_user)
        db_session.flush()

        expenses = db_session.execute(select(ExpenseORM)).scalars().all()
        assert len(expenses) == 1  # no duplicate

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_income_vs_expense_sign(self, MockPDB, db_session, seed_user, seed_account):
        """Positive amount → Expense, negative → Income."""
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[
                _make_plaid_txn("txn_exp", "ATM Withdrawal", 200.00),
                _make_plaid_txn("txn_inc", "Direct Deposit", -3000.00),
            ],
            modified=[],
            removed=[],
            next_cursor="c1",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        expenses = db_session.execute(select(ExpenseORM)).scalars().all()
        incomes = db_session.execute(select(IncomeORM)).scalars().all()

        assert len(expenses) == 1
        assert expenses[0].plaid_transaction_id == "txn_exp"
        assert expenses[0].amount == dollars_to_cents(200.00)

        assert len(incomes) == 1
        assert incomes[0].plaid_transaction_id == "txn_inc"
        assert incomes[0].amount == dollars_to_cents(3000.00)  # stored as positive

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_non_usd_transactions_are_skipped(self, MockPDB, db_session, seed_user, seed_account):
        """USD-only enforcement: a non-USD (EUR) or crypto transaction must NOT be
        imported, so the app's hardcoded USD labelling stays honest. The USD txn
        in the same batch is still imported."""
        account_id, token = seed_account

        eur = _make_plaid_txn("txn_eur", "Paris Cafe", 12.00)
        eur["iso_currency_code"] = "EUR"
        crypto = _make_plaid_txn("txn_btc", "Crypto Buy", 50.00)
        crypto["unofficial_currency_code"] = "BTC"
        usd = _make_plaid_txn("txn_usd", "Local Coffee", 4.50)
        usd["iso_currency_code"] = "USD"

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[eur, crypto, usd], modified=[], removed=[], next_cursor="c1",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        expenses = db_session.execute(select(ExpenseORM)).scalars().all()
        assert {e.plaid_transaction_id for e in expenses} == {"txn_usd"}


class TestSyncModified:
    """sync_transactions modifying existing rows."""

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_modified_updates_rows(self, MockPDB, db_session, seed_user, seed_account):
        """Modified transactions should update existing rows in place."""
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid

        # First sync: add a transaction
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[_make_plaid_txn("txn_mod", "Coffee Shop", 5.00)],
            modified=[],
            removed=[],
            next_cursor="c1",
        )
        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        # Second sync: Plaid revised the amount
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[],
            modified=[_make_plaid_txn("txn_mod", "Coffee Shop Revised", 5.75)],
            removed=[],
            next_cursor="c2",
        )
        svc2 = PlaidService(db_session)
        svc2.sync_all_tokens(seed_user)
        db_session.flush()

        expenses = db_session.execute(select(ExpenseORM)).scalars().all()
        assert len(expenses) == 1
        assert expenses[0].title == "Coffee Shop Revised"
        assert expenses[0].amount == dollars_to_cents(5.75)


class TestSyncRemoved:
    """sync_transactions removing rows."""

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_removed_deletes_rows(self, MockPDB, db_session, seed_user, seed_account):
        """Removed transactions should be deleted from the DB."""
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid

        # First sync: add
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[_make_plaid_txn("txn_del", "Pending Charge", 10.00)],
            modified=[],
            removed=[],
            next_cursor="c1",
        )
        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()
        assert db_session.execute(select(ExpenseORM)).scalars().all()

        # Second sync: Plaid removed the pending charge
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[],
            modified=[],
            removed=[{"transaction_id": "txn_del"}],
            next_cursor="c2",
        )
        svc2 = PlaidService(db_session)
        svc2.sync_all_tokens(seed_user)
        db_session.flush()

        expenses = db_session.execute(select(ExpenseORM)).scalars().all()
        assert len(expenses) == 0


class TestCursorPersistence:
    """Cursor should be persisted per token."""

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_cursor_persisted(self, MockPDB, db_session, seed_user, seed_account):
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[], modified=[], removed=[], next_cursor="cursor_xyz_123",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        db_session.refresh(token)
        assert token.cursor == "cursor_xyz_123"

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_cursor_passed_on_subsequent_sync(self, MockPDB, db_session, seed_user, seed_account):
        """The saved cursor should be passed to the next sync call."""
        account_id, token = seed_account
        token.cursor = "saved_cursor_abc"
        db_session.flush()

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[], modified=[], removed=[], next_cursor="new_cursor",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        # Verify the databridge was called with the previously saved cursor
        mock_plaid.sync_transactions.assert_called_once_with(
            token.key, "saved_cursor_abc"
        )


class TestEmptyAccountGuard:
    """Guard against empty institution data."""

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_no_matching_account_skips(self, MockPDB, db_session, seed_user):
        """A token with no matching local account should be skipped gracefully."""
        # Create a token but no matching account
        orphan_token = TokenORM(
            user_id=seed_user.id,
            name="Orphan Bank",
            key="access-orphan",
        )
        db_session.add(orphan_token)
        db_session.flush()

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid

        svc = PlaidService(db_session)
        summaries = svc.sync_all_tokens(seed_user)

        assert len(summaries) == 1
        assert summaries[0]["added"] == 0
        assert summaries[0]["modified"] == 0
        assert summaries[0]["removed"] == 0

        # sync_transactions should NOT have been called (no account to sync into)
        mock_plaid.sync_transactions.assert_not_called()


class TestCategoryExtraction:
    """Category extraction from Plaid transaction dicts."""

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_personal_finance_category_preferred(self, MockPDB, db_session, seed_user, seed_account):
        """personal_finance_category.primary should be preferred over legacy category."""
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid

        # Use a merchant with no keyword rule so this test isolates the
        # PFC-vs-legacy choice (not the categorizer's rules).
        txn = _make_plaid_txn("txn_cat", "City Cab Co", 25.00, category=["Travel"])
        txn["personal_finance_category"] = {"primary": "TRANSPORTATION", "detailed": "RIDE_SHARE"}

        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[txn], modified=[], removed=[], next_cursor="c1",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        # PFC "TRANSPORTATION" is preferred over legacy "Travel", and is
        # canonicalized onto the app's taxonomy ("Transportation").
        expense = db_session.execute(select(ExpenseORM)).scalar_one()
        assert expense.category == "Transportation"

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_legacy_category_fallback(self, MockPDB, db_session, seed_user, seed_account):
        """When personal_finance_category is None, fall back to legacy category list."""
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[_make_plaid_txn("txn_leg", "Walmart", 50.00, category=["Shops", "Supermarkets"])],
            modified=[],
            removed=[],
            next_cursor="c1",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        expense = db_session.execute(select(ExpenseORM)).scalar_one()
        assert expense.category == "Shops"

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_empty_category_defaults_to_other(self, MockPDB, db_session, seed_user, seed_account):
        """When both category sources are empty, default to 'Other'."""
        account_id, token = seed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid

        txn = _make_plaid_txn("txn_none", "Mystery", 10.00, category=[])
        txn["personal_finance_category"] = None

        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[txn], modified=[], removed=[], next_cursor="c1",
        )

        svc = PlaidService(db_session)
        svc.sync_all_tokens(seed_user)
        db_session.flush()

        expense = db_session.execute(select(ExpenseORM)).scalar_one()
        assert expense.category == "Other"
