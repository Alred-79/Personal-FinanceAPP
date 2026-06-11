"""Tests for the MCP vault boundary.

Covers:
1. Valid capability → correct, redacted data per resource.
2. Cross-user isolation: capability for user A never returns user B's rows.
3. Token enforcement: expired / forged / wrong-typ → VaultError.
4. Unknown resource → VaultError.
5. Read-only invariant: db.commit is never called.
6. Data-layer exception → VaultError (no traceback leak), rollback, audit denial.
7. Redaction: accounts keeps account id, drops user_id.
8. Per-account ownership guard propagates through vault.
"""

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest

from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.mcp import vault
from server.src.mcp.policy import issue_capability
from server.src.mcp.principal import Principal
from server.src.mcp.vault import VaultError
from server.src.settings import settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def principal_a():
    return Principal(user_id=1, key_id=10, scopes=frozenset(["read"]))


@pytest.fixture
def principal_b():
    return Principal(user_id=2, key_id=20, scopes=frozenset(["read"]))


@pytest.fixture
def token_a(principal_a):
    return issue_capability(principal_a, ["read"])


@pytest.fixture
def token_b(principal_b):
    return issue_capability(principal_b, ["read"])


@pytest.fixture
def patched_db(db_session, monkeypatch):
    """Monkeypatch vault.SessionLocal to return the test session without closing it."""
    class _NoClose:
        def __init__(self, s):
            self._s = s
        def __getattr__(self, name):
            return getattr(self._s, name)
        def close(self):
            pass

    monkeypatch.setattr(vault, "SessionLocal", lambda: _NoClose(db_session))
    return db_session


# ---------------------------------------------------------------------------
# Helpers to seed data
# ---------------------------------------------------------------------------

def _user(db, uid, username="alice", email="a@x.com"):
    u = UserORM(
        id=uid, username=username, full_name="Test", email=email,
        hashed_password="x", disabled=0,
    )
    db.add(u)
    db.flush()
    return u


def _account(db, uid, name="Checking", balance=100_00):
    a = AccountORM(name=name, type="checking", balance=balance, user_id=uid)
    db.add(a)
    db.flush()
    return a


def _expense(db, account_id, title="Latte", amount=5_00, date="2024-03-10",
             category="Food", recurrence=None):
    e = ExpenseORM(
        title=title, amount=amount, date=date, category=category,
        recurrence=recurrence, account_id=account_id,
    )
    db.add(e)
    db.flush()
    return e


def _income(db, account_id, title="Pay", amount=200_00, date="2024-03-01",
            category="Work"):
    i = IncomeORM(
        title=title, amount=amount, date=date, category=category,
        account_id=account_id,
    )
    db.add(i)
    db.flush()
    return i


def _goal(db, uid, name="Vacation", amount=1000_00, date="2025-12-31",
          progress=0, completed=0):
    g = GoalORM(
        name=name, description="", amount=amount, date=date,
        user_id=uid, completed=completed, progress=progress,
    )
    db.add(g)
    db.flush()
    return g


def _budget(db, uid, category="Food", monthly_limit=50000, rollover=0):
    b = BudgetORM(
        user_id=uid, category=category, monthly_limit=monthly_limit, rollover=rollover
    )
    db.add(b)
    db.flush()
    return b


# ---------------------------------------------------------------------------
# 1. Happy path — accounts resource
# ---------------------------------------------------------------------------

class TestVaultAccounts:
    def test_returns_account_list(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1, name="Savings", balance=200_00)
        result = vault.read(token_a, "accounts")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "Savings"

    def test_redaction_drops_user_id(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        result = vault.read(token_a, "accounts")
        assert "user_id" not in result[0]

    def test_redaction_keeps_id(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        result = vault.read(token_a, "accounts")
        assert "id" in result[0]

    def test_balance_is_dollars(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1, balance=12345)
        result = vault.read(token_a, "accounts")
        assert result[0]["balance"] == 123.45

    def test_empty_returns_empty_list(self, patched_db, token_a):
        _user(patched_db, 1)
        result = vault.read(token_a, "accounts")
        assert result == []


# ---------------------------------------------------------------------------
# 2. Cross-user isolation
# ---------------------------------------------------------------------------

class TestCrossUserIsolation:
    def _seed_both(self, db):
        _user(db, 1, "alice", "alice@x.com")
        _user(db, 2, "bob", "bob@x.com")
        a_acct = _account(db, 1, name="Alice Checking")
        b_acct = _account(db, 2, name="Bob Savings")
        _expense(db, a_acct.id, title="Alice coffee", category="Food")
        _expense(db, b_acct.id, title="Bob burger", category="Food")
        _goal(db, 1, name="Alice goal")
        _goal(db, 2, name="Bob goal")
        return a_acct, b_acct

    def test_accounts_scoped_to_token_user(self, patched_db, token_a, token_b):
        self._seed_both(patched_db)
        alice_result = vault.read(token_a, "accounts")
        bob_result = vault.read(token_b, "accounts")
        assert all(r["name"] == "Alice Checking" for r in alice_result)
        assert all(r["name"] == "Bob Savings" for r in bob_result)

    def test_tx_by_category_scoped(self, patched_db, token_a, token_b):
        self._seed_both(patched_db)
        alice_tx = vault.read(token_a, "tx_by_category", category="Food")["items"]
        bob_tx = vault.read(token_b, "tx_by_category", category="Food")["items"]
        assert all(r["title"] == "Alice coffee" for r in alice_tx)
        assert all(r["title"] == "Bob burger" for r in bob_tx)

    def test_goals_scoped(self, patched_db, token_a, token_b):
        self._seed_both(patched_db)
        assert all(r["name"] == "Alice goal" for r in vault.read(token_a, "goals"))
        assert all(r["name"] == "Bob goal" for r in vault.read(token_b, "goals"))

    def test_tx_per_account_cross_user_denied(self, patched_db, token_a):
        """Token for user A cannot fetch user B's account."""
        _user(patched_db, 1, "alice", "alice@x.com")
        _user(patched_db, 2, "bob", "bob@x.com")
        bob_acct = _account(patched_db, 2, name="Bob Savings")
        with pytest.raises(VaultError):
            vault.read(token_a, "tx_per_account", account_id=bob_acct.id)


# ---------------------------------------------------------------------------
# 3. Capability enforcement
# ---------------------------------------------------------------------------

class TestCapabilityEnforcement:
    def test_expired_token_raises_vault_error(self, patched_db):
        payload = {
            "uid": 1, "kid": 10, "scopes": ["read"],
            "typ": "mcp_capability",
            "exp": 1,  # far in the past
        }
        expired = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(VaultError):
            vault.read(expired, "ping")

    def test_forged_token_raises_vault_error(self, patched_db):
        forged = "this.is.not.a.valid.token"
        with pytest.raises(VaultError):
            vault.read(forged, "ping")

    def test_wrong_secret_raises_vault_error(self, patched_db):
        payload = {
            "uid": 1, "kid": 10, "scopes": ["read"],
            "typ": "mcp_capability",
            "exp": int(time.time()) + 3600,
        }
        bad_token = jwt.encode(payload, "wrong_secret", algorithm="HS256")
        with pytest.raises(VaultError):
            vault.read(bad_token, "ping")

    def test_wrong_typ_raises_vault_error(self, patched_db):
        payload = {
            "uid": 1, "kid": 10, "scopes": ["read"],
            "typ": "assistant_action",  # wrong type
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(VaultError):
            vault.read(token, "ping")

    def test_auth_access_token_rejected(self, patched_db):
        """A plain auth JWT (no typ) must not work as a capability."""
        payload = {
            "sub": "alice", "user_id": 1,
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(VaultError):
            vault.read(token, "ping")


# ---------------------------------------------------------------------------
# 4. Unknown resource
# ---------------------------------------------------------------------------

class TestUnknownResource:
    def test_unknown_resource_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        with pytest.raises(VaultError, match="Unknown resource"):
            vault.read(token_a, "not_a_real_resource")

    def test_empty_resource_name_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "")


# ---------------------------------------------------------------------------
# 5. Read-only invariant
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_commit_never_called_on_ping(self, patched_db, token_a, monkeypatch):
        _user(patched_db, 1)
        committed = []
        orig = patched_db.commit
        monkeypatch.setattr(patched_db, "commit", lambda: committed.append(1) or orig())
        vault.read(token_a, "ping")
        assert committed == []

    def test_commit_never_called_on_accounts(self, patched_db, token_a, monkeypatch):
        _user(patched_db, 1)
        _account(patched_db, 1)
        committed = []
        orig = patched_db.commit
        monkeypatch.setattr(patched_db, "commit", lambda: committed.append(1) or orig())
        vault.read(token_a, "accounts")
        assert committed == []

    def test_rollback_called_on_success(self, patched_db, token_a, monkeypatch):
        _user(patched_db, 1)
        rolled_back = []
        orig = patched_db.rollback
        monkeypatch.setattr(patched_db, "rollback", lambda: rolled_back.append(1) or orig())
        vault.read(token_a, "ping")
        assert rolled_back == [1]


# ---------------------------------------------------------------------------
# 6. Data-layer exception handling
# ---------------------------------------------------------------------------

class TestDataLayerException:
    def test_exception_becomes_vault_error(self, patched_db, token_a, monkeypatch):
        _user(patched_db, 1)
        monkeypatch.setattr(
            "server.src.mcp.vault.query_accounts",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DB melted")),
        )
        with pytest.raises(VaultError):
            vault.read(token_a, "accounts")

    def test_original_exception_not_leaked(self, patched_db, token_a, monkeypatch):
        _user(patched_db, 1)
        monkeypatch.setattr(
            "server.src.mcp.vault.query_accounts",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret internal detail")),
        )
        with pytest.raises(VaultError) as exc_info:
            vault.read(token_a, "accounts")
        assert "secret internal detail" not in str(exc_info.value)

    def test_rollback_called_on_exception(self, patched_db, token_a, monkeypatch):
        _user(patched_db, 1)
        monkeypatch.setattr(
            "server.src.mcp.vault.query_accounts",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        rolled_back = []
        orig = patched_db.rollback
        monkeypatch.setattr(patched_db, "rollback", lambda: rolled_back.append(1) or orig())
        with pytest.raises(VaultError):
            vault.read(token_a, "accounts")
        assert rolled_back == [1]

    def test_audit_records_denial_on_exception(self, patched_db, token_a, monkeypatch, caplog):
        import logging
        _user(patched_db, 1)
        monkeypatch.setattr(
            "server.src.mcp.vault.query_accounts",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with caplog.at_level(logging.INFO, logger="mcp.audit"):
            with pytest.raises(VaultError):
                vault.read(token_a, "accounts")
        assert any("deny" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 7. Redaction details
# ---------------------------------------------------------------------------

class TestRedaction:
    def test_accounts_no_user_id(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        result = vault.read(token_a, "accounts")
        for row in result:
            assert "user_id" not in row

    def test_accounts_keeps_id_field(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        result = vault.read(token_a, "accounts")
        assert result[0]["id"] == acct.id

    def test_budgets_drops_id(self, patched_db, token_a):
        _user(patched_db, 1)
        _budget(patched_db, 1, category="Food")
        result = vault.read(token_a, "budgets")
        for row in result:
            assert "id" not in row
            assert "user_id" not in row

    def test_budgets_keeps_category(self, patched_db, token_a):
        _user(patched_db, 1)
        _budget(patched_db, 1, category="Transport")
        result = vault.read(token_a, "budgets")
        assert result[0]["category"] == "Transport"

    def test_goals_no_user_id(self, patched_db, token_a):
        _user(patched_db, 1)
        _goal(patched_db, 1)
        result = vault.read(token_a, "goals")
        for row in result:
            assert "user_id" not in row

    def test_spend_summary_no_user_id(self, patched_db, token_a):
        _user(patched_db, 1)
        result = vault.read(token_a, "spend_summary")
        assert "user_id" not in result


# ---------------------------------------------------------------------------
# 8. Happy path — remaining resources
# ---------------------------------------------------------------------------

class TestRemainingResources:
    def test_ping_returns_user_id(self, patched_db, token_a):
        _user(patched_db, 1)
        result = vault.read(token_a, "ping")
        assert result == {"user_id": 1}

    def test_context_returns_annotated_snapshot(self, patched_db, token_a):
        _user(patched_db, 1)
        result = vault.read(token_a, "context")
        assert isinstance(result, dict)
        assert result.get("schema_version") == "1.0"
        assert "spendable" in result
        assert "cashflow_forecast" in result

    def test_tx_by_date_returns_list(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _expense(patched_db, acct.id, date="2024-03-10")
        result = vault.read(token_a, "tx_by_date", start="2024-03-01", end="2024-03-31")
        assert isinstance(result, dict)
        assert result["has_more"] is False
        assert result["next_offset"] is None
        assert len(result["items"]) == 1

    def test_tx_by_date_missing_params_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "tx_by_date", start="2024-03-01")

    def test_tx_by_category_returns_list(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _expense(patched_db, acct.id, category="Food")
        result = vault.read(token_a, "tx_by_category", category="Food")
        assert len(result["items"]) == 1

    def test_tx_by_category_missing_param_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "tx_by_category")

    def test_tx_per_account_owned(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _expense(patched_db, acct.id)
        result = vault.read(token_a, "tx_per_account", account_id=acct.id)
        assert len(result["items"]) == 1

    def test_tx_per_account_missing_param_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "tx_per_account")

    def test_goals_returns_list(self, patched_db, token_a):
        _user(patched_db, 1)
        _goal(patched_db, 1, name="Trip")
        result = vault.read(token_a, "goals")
        assert result[0]["name"] == "Trip"

    def test_spend_summary_has_keys(self, patched_db, token_a):
        _user(patched_db, 1)
        result = vault.read(token_a, "spend_summary")
        assert "weekly_max_budget" in result
        assert "weekly_spend" in result

    def test_budgets_returns_list(self, patched_db, token_a):
        _user(patched_db, 1)
        _budget(patched_db, 1, category="Food")
        result = vault.read(token_a, "budgets")
        assert isinstance(result, list)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 9. Audit trail
# ---------------------------------------------------------------------------

class TestAudit:
    def test_allow_audit_on_success(self, patched_db, token_a, caplog):
        import logging
        _user(patched_db, 1)
        with caplog.at_level(logging.INFO, logger="mcp.audit"):
            vault.read(token_a, "ping")
        assert any("allow" in r.message for r in caplog.records)

    def test_deny_audit_on_bad_token(self, patched_db, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="mcp.audit"):
            with pytest.raises(VaultError):
                vault.read("bad.token.here", "ping")
        assert any("deny" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 10. Category matching + discovery (fix B)
# ---------------------------------------------------------------------------

class TestCategoryMatching:
    def test_lowercase_input_matches_canonical(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _expense(patched_db, acct.id, category="Food")
        # "food" must resolve to the stored canonical "Food".
        result = vault.read(token_a, "tx_by_category", category="food")
        assert len(result["items"]) == 1

    def test_food_and_drink_distinct_from_food(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _expense(patched_db, acct.id, title="Latte", category="Food")
        _expense(patched_db, acct.id, title="Dinner", category="Food and Drink")
        patched_db.commit()  # vault.read rolls back its session; persist seed first
        food = vault.read(token_a, "tx_by_category", category="Food")["items"]
        fad = vault.read(token_a, "tx_by_category", category="food and drink")["items"]
        assert [r["title"] for r in food] == ["Latte"]
        assert [r["title"] for r in fad] == ["Dinner"]

    def test_categories_resource_lists_canonical_and_present(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _expense(patched_db, acct.id, category="Food")
        _income(patched_db, acct.id, category="Work")
        result = vault.read(token_a, "categories")
        assert "Food" in result["canonical"]
        assert result["present"] == ["Food", "Work"]


# ---------------------------------------------------------------------------
# 11. Date validation (fix C)
# ---------------------------------------------------------------------------

class TestDateValidation:
    def test_valid_range_returns_page(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _expense(patched_db, acct.id, date="2024-03-10")
        result = vault.read(token_a, "tx_by_date", start="2024-03-01", end="2024-03-31")
        assert len(result["items"]) == 1

    def test_malformed_date_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "tx_by_date", start="2024-13-99", end="2024-03-31")

    def test_inverted_range_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "tx_by_date", start="2024-12-31", end="2024-01-01")


# ---------------------------------------------------------------------------
# 12. Pagination (fix D)
# ---------------------------------------------------------------------------

class TestPagination:
    def _seed(self, db, n):
        _user(db, 1)
        acct = _account(db, 1)
        for i in range(n):
            _expense(db, acct.id, title=f"tx{i}", date=f"2024-03-{i + 1:02d}")
        return acct

    def test_limit_bounds_items_and_sets_has_more(self, patched_db, token_a):
        self._seed(patched_db, 5)
        page = vault.read(
            token_a, "tx_by_date",
            start="2024-03-01", end="2024-03-31", limit=2, offset=0,
        )
        assert len(page["items"]) == 2
        assert page["has_more"] is True
        assert page["next_offset"] == 2

    def test_paging_with_offset_reaches_last_page(self, patched_db, token_a):
        self._seed(patched_db, 5)
        page = vault.read(
            token_a, "tx_by_date",
            start="2024-03-01", end="2024-03-31", limit=2, offset=4,
        )
        assert len(page["items"]) == 1
        assert page["has_more"] is False
        assert page["next_offset"] is None

    def test_limit_clamped_to_max(self, patched_db, token_a):
        # An over-large limit is clamped, not an error.
        self._seed(patched_db, 3)
        page = vault.read(
            token_a, "tx_by_date",
            start="2024-03-01", end="2024-03-31", limit=10_000, offset=0,
        )
        assert len(page["items"]) == 3

    def test_negative_offset_rejected(self, patched_db, token_a):
        self._seed(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(
                token_a, "tx_by_date",
                start="2024-03-01", end="2024-03-31", offset=-1,
            )


# ---------------------------------------------------------------------------
# 13. Spend-summary clarity (fix E)
# ---------------------------------------------------------------------------

class TestSpendSummaryClarity:
    def test_has_work_income_false_with_annotations(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        result = vault.read(token_a, "spend_summary")
        assert result["has_work_income"] is False
        assert "caveats" in result and result["caveats"]
        assert result["period"] == "P14D"
        assert "method" in result

    def test_has_work_income_true_when_work_income_present(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        _income(patched_db, acct.id, category="Work")
        result = vault.read(token_a, "spend_summary")
        assert result["has_work_income"] is True
