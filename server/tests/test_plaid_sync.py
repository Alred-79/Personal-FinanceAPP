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
    account_id: str | None = None,
) -> dict:
    """Build a minimal Plaid transaction dict.

    *account_id* is the Plaid account id the txn belongs to (Step 08 routing).
    """
    txn = {
        "transaction_id": txn_id,
        "name": name,
        "amount": amount,
        "date": date,
        "category": ["Shopping"] if category is None else category,
        "personal_finance_category": None,
    }
    if account_id is not None:
        txn["account_id"] = account_id
    return txn


class _FakeBalanceAccount:
    """A stand-in for a Plaid balance account object with ``.to_dict()``."""

    def __init__(self, account_id: str, available: float | None, current: float | None):
        self._d = {
            "account_id": account_id,
            "type": "depository",
            "name": account_id,
            "balances": {"available": available, "current": current},
        }

    def to_dict(self) -> dict:
        return self._d


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


# ── Step 08: integrity ────────────────────────────────────────────────────────


@pytest.fixture
def seed_id_keyed_account(db_session, seed_user):
    """A Plaid token + a local account keyed by ``plaid_account_id`` (Step 08)."""
    token = TokenORM(
        user_id=seed_user.id,
        name="Chase",
        # An encrypted token at rest; sync decrypts before the Plaid call.
        key=_enc("access-sandbox-fake"),
        cursor=None,
    )
    db_session.add(token)
    db_session.flush()

    account = AccountORM(
        name="Chase Checking",
        type="depository",
        balance=0,
        plaid_account_id="plaid_acct_A",
        user_id=seed_user.id,
    )
    db_session.add(account)
    db_session.flush()
    return account, token


def _enc(plaintext: str) -> str:
    from server.src.services import plaid_crypto

    return plaid_crypto.encrypt(plaintext)


class TestTokenEncryption:
    def test_access_token_encrypted_at_rest(self):
        """The stored ciphertext differs from the plaintext, and round-trips."""
        from server.src.services import plaid_crypto

        plaintext = "access-sandbox-super-secret"
        stored = plaid_crypto.encrypt(plaintext)
        assert stored != plaintext
        assert plaintext not in stored  # not merely prefixed plaintext
        assert plaid_crypto.is_encrypted(stored)
        assert plaid_crypto.decrypt(stored) == plaintext

    def test_legacy_plaintext_token_tolerated(self):
        """A pre-migration plaintext token decrypts to itself (no crash)."""
        from server.src.services import plaid_crypto

        assert not plaid_crypto.is_encrypted("access-plain")
        assert plaid_crypto.decrypt("access-plain") == "access-plain"

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_decrypts_token_for_plaid_call(
        self, MockPDB, db_session, seed_user, seed_id_keyed_account
    ):
        """sync passes the DECRYPTED token to the Plaid client, not ciphertext."""
        account, token = seed_id_keyed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[], modified=[], removed=[], next_cursor="c1",
        )
        mock_plaid.get_balance.return_value = []

        PlaidService(db_session).sync_all_tokens(seed_user)

        called_token = mock_plaid.sync_transactions.call_args[0][0]
        assert called_token == "access-sandbox-fake"  # decrypted
        assert not called_token.startswith("enc:")


class TestMultiAccountRouting:
    @patch("server.src.services.plaid_service.PlaidClient")
    def test_multi_account_item_routes_by_account_id(
        self, MockPDB, db_session, seed_user, seed_id_keyed_account
    ):
        """A batch spanning two Plaid accounts lands in the two local accounts."""
        account_a, token = seed_id_keyed_account
        account_b = AccountORM(
            name="Chase Savings",
            type="depository",
            balance=0,
            plaid_account_id="plaid_acct_B",
            user_id=seed_user.id,
        )
        db_session.add(account_b)
        db_session.flush()

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[
                _make_plaid_txn("t_a1", "Coffee", 4.50, account_id="plaid_acct_A"),
                _make_plaid_txn("t_b1", "Card Payment", 30.00, account_id="plaid_acct_B"),
            ],
            modified=[],
            removed=[],
            next_cursor="c1",
        )
        mock_plaid.get_balance.return_value = []

        PlaidService(db_session).sync_all_tokens(seed_user)
        db_session.flush()

        by_acct = {
            e.account_id: e.plaid_transaction_id
            for e in db_session.execute(select(ExpenseORM)).scalars().all()
        }
        assert by_acct == {account_a.id: "t_a1", account_b.id: "t_b1"}

    @patch("server.src.services.plaid_service.PlaidClient")
    def test_renamed_account_still_syncs(
        self, MockPDB, db_session, seed_user, seed_id_keyed_account
    ):
        """Renaming the local account doesn't break id-keyed routing."""
        account, token = seed_id_keyed_account
        account.name = "Totally Different Name"
        db_session.flush()

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[_make_plaid_txn("t1", "Coffee", 4.50, account_id="plaid_acct_A")],
            modified=[],
            removed=[],
            next_cursor="c1",
        )
        mock_plaid.get_balance.return_value = []

        PlaidService(db_session).sync_all_tokens(seed_user)
        db_session.flush()

        rows = db_session.execute(select(ExpenseORM)).scalars().all()
        assert len(rows) == 1
        assert rows[0].account_id == account.id


class TestDedupConstraint:
    @patch("server.src.services.plaid_service.PlaidClient")
    def test_duplicate_plaid_transaction_id_is_noop(
        self, MockPDB, db_session, seed_user, seed_id_keyed_account
    ):
        """Syncing the same txn id twice yields one row (IntegrityError path)."""
        account, token = seed_id_keyed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.get_balance.return_value = []
        txns = [_make_plaid_txn("dup", "Once", 19.99, account_id="plaid_acct_A")]
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=txns, modified=[], removed=[], next_cursor="c1",
        )
        PlaidService(db_session).sync_all_tokens(seed_user)
        db_session.flush()

        # Second sync re-presents the SAME id (cursor replay / race).
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=txns, modified=[], removed=[], next_cursor="c2",
        )
        PlaidService(db_session).sync_all_tokens(seed_user)
        db_session.flush()

        rows = db_session.execute(select(ExpenseORM)).scalars().all()
        assert len(rows) == 1

    def test_partial_unique_index_allows_null_manual_rows(self, db_session, seed_user):
        """Two manual rows (NULL plaid_transaction_id) don't collide."""
        acct = AccountORM(
            name="Manual", type="checking", balance=0, user_id=seed_user.id
        )
        db_session.add(acct)
        db_session.flush()
        db_session.add_all(
            [
                ExpenseORM(title="a", amount=100, date="2026-01-01", category="X", account_id=acct.id),
                ExpenseORM(title="b", amount=200, date="2026-01-02", category="X", account_id=acct.id),
            ]
        )
        db_session.flush()  # would raise if NULLs collided
        assert len(db_session.execute(select(ExpenseORM)).scalars().all()) == 2


class TestBalanceRefresh:
    @patch("server.src.services.plaid_service.PlaidClient")
    def test_sync_updates_account_balance(
        self, MockPDB, db_session, seed_user, seed_id_keyed_account
    ):
        """After sync, the local balance equals Plaid's reported balance."""
        account, token = seed_id_keyed_account

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[], modified=[], removed=[], next_cursor="c1",
        )
        mock_plaid.get_balance.return_value = [
            _FakeBalanceAccount("plaid_acct_A", available=1234.56, current=1300.00)
        ]

        PlaidService(db_session).sync_all_tokens(seed_user)
        db_session.flush()
        db_session.refresh(account)
        assert account.balance == dollars_to_cents(1234.56)  # available preferred


class TestPerTokenIsolation:
    @patch("server.src.services.plaid_service.PlaidClient")
    def test_one_failing_token_does_not_abort_others(
        self, MockPDB, db_session, seed_user
    ):
        """First token raises; the second still syncs and its rows persist."""
        # Token 1: will fail on sync.
        t1 = TokenORM(user_id=seed_user.id, name="BadBank", key=_enc("k1"))
        a1 = AccountORM(
            name="BadBank", type="depository", balance=0,
            plaid_account_id="acct_bad", user_id=seed_user.id,
        )
        # Token 2: healthy.
        t2 = TokenORM(user_id=seed_user.id, name="GoodBank", key=_enc("k2"))
        a2 = AccountORM(
            name="GoodBank", type="depository", balance=0,
            plaid_account_id="acct_good", user_id=seed_user.id,
        )
        db_session.add_all([t1, a1, t2, a2])
        db_session.flush()

        mock_plaid = MagicMock()
        MockPDB.return_value = mock_plaid
        mock_plaid.get_balance.return_value = []

        good_result = SyncResult(
            added=[_make_plaid_txn("g1", "Lunch", 12.00, account_id="acct_good")],
            modified=[],
            removed=[],
            next_cursor="cg",
        )

        def _sync(decrypted_token, cursor):
            if decrypted_token == "k1":
                raise RuntimeError("ITEM_LOGIN_REQUIRED")
            return good_result

        mock_plaid.sync_transactions.side_effect = _sync

        summaries = PlaidService(db_session).sync_all_tokens(seed_user)
        db_session.flush()

        # The good token's row is present despite the bad token failing.
        rows = db_session.execute(select(ExpenseORM)).scalars().all()
        assert [r.plaid_transaction_id for r in rows] == ["g1"]
        # Per-token summary reflects one error, one success.
        errored = [s for s in summaries if s.get("error")]
        assert len(errored) == 1 and errored[0]["token"] == "BadBank"
