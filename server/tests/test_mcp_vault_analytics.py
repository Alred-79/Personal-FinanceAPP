"""Tests for the Tier-1 analytical MCP vault resources.

Covers the four read resources added to widen the agent surface beyond the
original accounts/transactions/goals/budgets/context set:

  * ``forecast``       — annotated probabilistic cashflow projection
  * ``net_worth``      — current total + read-only snapshot series
  * ``subscriptions``  — detected recurring charges
  * ``what_if``        — baseline-vs-scenario diff from an overlay spec

Each must: return the documented shape, stay user-scoped, stay read-only (the
vault never commits), and turn bad input into a ``VaultError`` rather than a
500/traceback. Reuses the same seeding style as ``test_mcp_vault.py``.
"""

import pytest

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.mcp import vault
from server.src.mcp.policy import issue_capability
from server.src.mcp.principal import Principal
from server.src.mcp.vault import VaultError


# ---------------------------------------------------------------------------
# Fixtures (mirror test_mcp_vault.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def principal_a():
    return Principal(user_id=1, key_id=10, scopes=frozenset(["read"]))


@pytest.fixture
def token_a(principal_a):
    return issue_capability(principal_a, ["read"])


@pytest.fixture
def patched_db(db_session, monkeypatch):
    class _NoClose:
        def __init__(self, s):
            self._s = s

        def __getattr__(self, name):
            return getattr(self._s, name)

        def close(self):
            pass

    monkeypatch.setattr(vault, "SessionLocal", lambda: _NoClose(db_session))
    return db_session


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


def _expense(db, account_id, title="Rent", amount=50_00, date="2024-03-10",
             category="Housing", recurrence=None):
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


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

class TestForecastResource:
    def test_returns_annotated_projection(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1, balance=500_00)
        result = vault.read(token_a, "forecast", days=30)
        assert isinstance(result, dict)
        assert "horizon" in result and result["horizon"]["days"] == 30
        assert "starting_balance" in result
        assert "lowest_balance" in result
        assert "overdraft_probability" in result
        # Self-annotating, like the rest of the MCP surface.
        assert result["method"]
        assert result["assumptions"]
        assert result["caveats"]

    def test_default_days_when_unspecified(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        result = vault.read(token_a, "forecast")
        assert result["horizon"]["days"] > 0

    def test_rejects_non_integer_days(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "forecast", days="lots")

    def test_rejects_non_positive_days(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "forecast", days=0)


# ---------------------------------------------------------------------------
# net_worth
# ---------------------------------------------------------------------------

class TestNetWorthResource:
    def test_current_total_is_sum_of_balances(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1, name="A", balance=300_00)
        _account(patched_db, 1, name="B", balance=150_00)
        result = vault.read(token_a, "net_worth")
        assert result["current"] == 450.0
        assert isinstance(result["series"], list)

    def test_scoped_to_user(self, patched_db, token_a):
        _user(patched_db, 1, "alice", "alice@x.com")
        _user(patched_db, 2, "bob", "bob@x.com")
        _account(patched_db, 1, balance=100_00)
        _account(patched_db, 2, balance=999_00)
        result = vault.read(token_a, "net_worth")
        assert result["current"] == 100.0

    def test_does_not_write_a_snapshot(self, patched_db, token_a, monkeypatch):
        """The vault is read-only — net_worth must not commit a snapshot."""
        _user(patched_db, 1)
        _account(patched_db, 1, balance=100_00)
        committed = []
        orig = patched_db.commit
        monkeypatch.setattr(
            patched_db, "commit", lambda: committed.append(1) or orig()
        )
        vault.read(token_a, "net_worth")
        assert committed == []


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------

class TestSubscriptionsResource:
    def test_returns_list(self, patched_db, token_a):
        _user(patched_db, 1)
        acct = _account(patched_db, 1)
        # Three monthly Netflix charges → a detected subscription.
        for m in ("01", "02", "03"):
            _expense(
                patched_db, acct.id, title="Netflix", amount=15_99,
                date=f"2024-{m}-05", category="Entertainment",
            )
        result = vault.read(token_a, "subscriptions")
        assert isinstance(result, list)

    def test_scoped_to_user(self, patched_db, token_a):
        _user(patched_db, 1, "alice", "alice@x.com")
        _user(patched_db, 2, "bob", "bob@x.com")
        bob_acct = _account(patched_db, 2)
        for m in ("01", "02", "03"):
            _expense(
                patched_db, bob_acct.id, title="Spotify", amount=9_99,
                date=f"2024-{m}-05",
            )
        # Alice has no transactions → no subscriptions, never sees Bob's.
        result = vault.read(token_a, "subscriptions")
        assert all("Spotify" != s.get("title") for s in result)


# ---------------------------------------------------------------------------
# what_if
# ---------------------------------------------------------------------------

class TestWhatIfResource:
    def test_empty_overlay_diffs_to_baseline(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1, balance=500_00)
        result = vault.read(token_a, "what_if", overlay={})
        assert "baseline" in result
        assert "scenario" in result
        assert "delta" in result["scenario"]

    def test_missing_overlay_raises(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "what_if")

    def test_malformed_overlay_raises_vault_error(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "what_if", overlay={"discrete_flows": "not-a-list"})

    def test_overlay_must_be_object(self, patched_db, token_a):
        _user(patched_db, 1)
        _account(patched_db, 1)
        with pytest.raises(VaultError):
            vault.read(token_a, "what_if", overlay="nope")
