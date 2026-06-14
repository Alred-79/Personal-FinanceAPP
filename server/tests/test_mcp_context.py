"""Tests for the budget://context MCP resource.

Coverage:
1. Shape/schema: top-level keys, schema_version, generated_at (UTC), currency.
2. Annotation invariant: every computed block has non-empty method + assumptions.
3. Anti-misrepresentation: spendable.period == "P14D"; assumptions mention "NOT monthly";
   forecast assumptions are honest about projected income + discretionary burn.
4. Correctness: seeded fixture → spendable.value matches SpendService output;
   budgets match BudgetService.summarize; amounts are dollars.
5. Empty-data user: valid, fully-annotated snapshot with zeros/empties, no crash.
6. Reserved keys: baselines is None; each goal item feasibility is None.
7. e2e + isolation: vault.read("context") returns correct snapshot; scope
   enforcement; user A's snapshot never contains user B's data.
"""

import pytest
from datetime import datetime

from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.mcp.context import (
    ContextBuilder,
    SCHEMA_VERSION,
    _SPENDABLE_PERIOD,
)
from server.src.mcp.policy import PolicyError, require
from server.src.mcp.principal import Principal
from server.src.models import UserInDB
from server.src.services.budget_service import BudgetService
from server.src.services.spend_service import SpendService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, username="alice", savings_percent=10):
    u = UserORM(
        username=username,
        full_name=username.title(),
        email=f"{username}@example.com",
        hashed_password="hashed",
        disabled=0,
        spend_warning=80,
        savings_percent=savings_percent,
    )
    db.add(u)
    db.flush()
    return u


def _make_account(db, user_id, balance_cents=0):
    a = AccountORM(name="Checking", type="checking", balance=balance_cents, user_id=user_id)
    db.add(a)
    db.flush()
    return a


def _make_income(db, account_id, amount_cents, category="Work", date="2026-05-01"):
    i = IncomeORM(
        title="Paycheck", amount=amount_cents, date=date,
        category=category, account_id=account_id,
    )
    db.add(i)
    db.flush()
    return i


def _make_budget(db, user_id, category="Food", monthly_limit_cents=50_000):
    b = BudgetORM(
        user_id=user_id, category=category,
        monthly_limit=monthly_limit_cents, rollover=0,
    )
    db.add(b)
    db.flush()
    return b


def _make_goal(db, user_id, name="Emergency Fund",
               amount_cents=500_000, progress_cents=120_000, date="2026-12-31"):
    g = GoalORM(
        name=name, description="", amount=amount_cents, date=date,
        user_id=user_id, completed=0, progress=progress_cents,
    )
    db.add(g)
    db.flush()
    return g


def _build(db, uid):
    return ContextBuilder(db).build(uid)


# ---------------------------------------------------------------------------
# 1. Shape / schema
# ---------------------------------------------------------------------------

class TestShape:
    def test_top_level_keys_present(self, db_session):
        uid = _make_user(db_session).id
        s = _build(db_session, uid)
        for key in ("schema_version", "generated_at", "currency", "spendable",
                    "cashflow_forecast", "budgets", "goals", "baselines"):
            assert key in s, f"missing top-level key: {key}"

    def test_schema_version(self, db_session):
        uid = _make_user(db_session).id
        assert _build(db_session, uid)["schema_version"] == SCHEMA_VERSION

    def test_generated_at_is_utc_aware(self, db_session):
        uid = _make_user(db_session).id
        raw = _build(db_session, uid)["generated_at"]
        dt = datetime.fromisoformat(raw)
        assert dt.tzinfo is not None, "generated_at must be timezone-aware"
        assert dt.utcoffset().total_seconds() == 0, "generated_at must be UTC"

    def test_currency_is_usd(self, db_session):
        uid = _make_user(db_session).id
        assert _build(db_session, uid)["currency"] == "USD"

    def test_spendable_block_shape(self, db_session):
        uid = _make_user(db_session).id
        sp = _build(db_session, uid)["spendable"]
        for key in ("value", "unit", "period", "method", "assumptions", "caveats"):
            assert key in sp, f"spendable missing key: {key}"

    def test_cashflow_forecast_block_shape(self, db_session):
        uid = _make_user(db_session).id
        cf = _build(db_session, uid)["cashflow_forecast"]
        for key in ("horizon", "starting_balance", "ending_balance",
                    "lowest_balance", "will_go_negative", "method", "assumptions", "caveats"):
            assert key in cf, f"cashflow_forecast missing key: {key}"

    def test_cashflow_forecast_exposes_overdraft_outlook(self, db_session):
        """The MCP context surfaces the probabilistic outlook so the assistant
        can speak to overdraft risk: a probability, a daily burn, and a band on
        the trough."""
        uid = _make_user(db_session).id
        cf = _build(db_session, uid)["cashflow_forecast"]
        assert "overdraft_probability" in cf
        assert 0.0 <= cf["overdraft_probability"] <= 1.0
        assert "daily_discretionary_burn" in cf
        band = cf["lowest_balance"]["band"]
        assert band["low"] <= band["median"] <= band["high"]

    def test_budgets_block_shape(self, db_session):
        uid = _make_user(db_session).id
        bud = _build(db_session, uid)["budgets"]
        for key in ("as_of", "scope", "method", "assumptions", "categories"):
            assert key in bud, f"budgets missing key: {key}"

    def test_goals_block_shape(self, db_session):
        uid = _make_user(db_session).id
        g = _build(db_session, uid)["goals"]
        for key in ("method", "assumptions", "items"):
            assert key in g, f"goals missing key: {key}"


# ---------------------------------------------------------------------------
# 2. Annotation invariant
# ---------------------------------------------------------------------------

class TestAnnotationInvariant:
    def test_every_computed_block_has_method_and_assumptions(self, db_session):
        uid = _make_user(db_session).id
        s = _build(db_session, uid)
        for block_name in ("spendable", "cashflow_forecast", "budgets", "goals"):
            block = s[block_name]
            assert block.get("method"), f"{block_name}.method is empty"
            assert block.get("assumptions"), f"{block_name}.assumptions is empty"

    def test_assumptions_are_non_empty_strings(self, db_session):
        uid = _make_user(db_session).id
        s = _build(db_session, uid)
        for block_name in ("spendable", "cashflow_forecast", "budgets", "goals"):
            for assumption in s[block_name]["assumptions"]:
                assert isinstance(assumption, str) and assumption.strip(), \
                    f"{block_name} contains blank assumption: {assumption!r}"


# ---------------------------------------------------------------------------
# 3. Anti-misrepresentation guards
# ---------------------------------------------------------------------------

class TestAntiMisrepresentation:
    def test_spendable_period_is_p14d(self, db_session):
        uid = _make_user(db_session).id
        assert _build(db_session, uid)["spendable"]["period"] == "P14D"

    def test_spendable_period_constant_matches(self, db_session):
        uid = _make_user(db_session).id
        assert _build(db_session, uid)["spendable"]["period"] == _SPENDABLE_PERIOD

    def test_spendable_assumptions_mention_not_monthly(self, db_session):
        uid = _make_user(db_session).id
        text = " ".join(_build(db_session, uid)["spendable"]["assumptions"])
        assert "NOT monthly" in text

    def test_forecast_assumptions_mention_recurring_expenses(self, db_session):
        uid = _make_user(db_session).id
        text = " ".join(_build(db_session, uid)["cashflow_forecast"]["assumptions"])
        assert "expenses" in text.lower()

    def test_forecast_assumptions_are_honest_about_income_and_burn(self, db_session):
        """The narration must reflect the real method: income IS projected, and
        the forecast drains a discretionary burn (the old 'no income' /
        'expenses only' copy was stale and is now corrected)."""
        uid = _make_user(db_session).id
        text = " ".join(
            _build(db_session, uid)["cashflow_forecast"]["assumptions"]
        ).lower()
        assert "income" in text
        assert "burn" in text
        assert "no income" not in text  # the old lie must be gone


# ---------------------------------------------------------------------------
# 4. Correctness
# ---------------------------------------------------------------------------

class TestCorrectness:
    def test_spendable_value_matches_spend_service(self, db_session):
        user = _make_user(db_session, savings_percent=0)
        acct = _make_account(db_session, user.id, balance_cents=500_000)
        _make_income(db_session, acct.id, amount_cents=200_000)
        db_session.commit()

        pydantic_user = UserInDB(
            id=user.id, username=user.username, email=user.email,
            full_name=user.full_name, disabled=bool(user.disabled),
            hashed_password=user.hashed_password,
            savings_percent=0, spend_warning=user.spend_warning,
        )
        expected = SpendService(db_session).get_budget_allotment(pydantic_user)
        assert _build(db_session, user.id)["spendable"]["value"] == expected

    def test_budgets_match_service(self, db_session):
        user = _make_user(db_session)
        _make_budget(db_session, user.id, category="Groceries", monthly_limit_cents=60_000)
        db_session.commit()

        expected = BudgetService(db_session).summarize(user.id)
        cats = _build(db_session, user.id)["budgets"]["categories"]
        assert len(cats) == len(expected)
        assert cats[0]["category"] == expected[0]["category"]
        assert cats[0]["monthly_limit"] == expected[0]["monthly_limit"]

    def test_amounts_are_dollars_not_cents(self, db_session):
        user = _make_user(db_session, savings_percent=0)
        acct = _make_account(db_session, user.id, balance_cents=100_000)  # $1000
        _make_income(db_session, acct.id, amount_cents=200_000)           # $2000 paycheck
        db_session.commit()

        s = _build(db_session, user.id)
        assert s["cashflow_forecast"]["starting_balance"] == 1000.0
        assert s["spendable"]["value"] == 1000.0  # 2000/2 with no savings/fixed

    def test_goal_items_populated_correctly(self, db_session):
        user = _make_user(db_session)
        _make_goal(db_session, user.id, name="Holiday",
                   amount_cents=500_000, progress_cents=100_000)
        db_session.commit()

        items = _build(db_session, user.id)["goals"]["items"]
        assert len(items) == 1
        g = items[0]
        assert g["name"] == "Holiday"
        assert g["target_amount"] == 5000.0
        assert g["progress"] == 1000.0
        assert g["remaining"] == 4000.0


# ---------------------------------------------------------------------------
# 5. Empty-data user
# ---------------------------------------------------------------------------

class TestEmptyDataUser:
    def test_no_crash_for_new_user(self, db_session):
        uid = _make_user(db_session).id
        db_session.commit()
        s = _build(db_session, uid)
        assert s["spendable"]["value"] == 0
        assert s["cashflow_forecast"]["starting_balance"] == 0
        assert s["cashflow_forecast"]["will_go_negative"] is False
        assert s["budgets"]["categories"] == []
        assert s["goals"]["items"] == []

    def test_empty_user_snapshot_still_fully_annotated(self, db_session):
        uid = _make_user(db_session).id
        db_session.commit()
        s = _build(db_session, uid)
        for block_name in ("spendable", "cashflow_forecast", "budgets", "goals"):
            assert s[block_name].get("method"), \
                f"{block_name}.method missing for empty-data user"
            assert s[block_name].get("assumptions"), \
                f"{block_name}.assumptions missing for empty-data user"


# ---------------------------------------------------------------------------
# 6. Reserved keys
# ---------------------------------------------------------------------------

class TestReservedKeys:
    def test_baselines_is_null(self, db_session):
        uid = _make_user(db_session).id
        assert _build(db_session, uid)["baselines"] is None

    def test_goal_feasibility_is_null(self, db_session):
        user = _make_user(db_session)
        _make_goal(db_session, user.id)
        db_session.commit()
        items = _build(db_session, user.id)["goals"]["items"]
        assert len(items) == 1
        assert items[0]["feasibility"] is None


# ---------------------------------------------------------------------------
# 7. e2e + isolation
# ---------------------------------------------------------------------------

class TestE2eAndIsolation:
    def test_scope_enforcement_denies_wrong_scope(self):
        principal = Principal(user_id=1, key_id=1, scopes=frozenset(["read:accounts"]))
        with pytest.raises(PolicyError):
            require(principal, "read:context")

    def test_read_context_scope_is_accepted(self):
        principal = Principal(user_id=1, key_id=1, scopes=frozenset(["read:context"]))
        require(principal, "read:context")  # must not raise

    def test_vault_read_context_returns_correct_snapshot(self, db_session, monkeypatch):
        from server.src.mcp import vault as vault_mod
        from server.src.mcp.policy import issue_capability

        class _NoClose:
            def __init__(self, s): self._s = s
            def __getattr__(self, n): return getattr(self._s, n)
            def close(self): pass

        monkeypatch.setattr(vault_mod, "SessionLocal", lambda: _NoClose(db_session))

        user = _make_user(db_session)
        db_session.commit()

        principal = Principal(user_id=user.id, key_id=1, scopes=frozenset(["read:context"]))
        cap = issue_capability(principal, ["read:context"])
        result = vault_mod.read(cap, "context")

        assert isinstance(result, dict)
        assert result["schema_version"] == SCHEMA_VERSION
        assert "spendable" in result
        assert "cashflow_forecast" in result

    def test_user_a_snapshot_excludes_user_b_data(self, db_session):
        user_a = _make_user(db_session, username="alice")
        user_b = _make_user(db_session, username="bob")
        acct_a = _make_account(db_session, user_a.id, balance_cents=100_000)
        acct_b = _make_account(db_session, user_b.id, balance_cents=999_000)
        _make_income(db_session, acct_a.id, amount_cents=200_000)
        _make_income(db_session, acct_b.id, amount_cents=800_000)
        _make_budget(db_session, user_a.id, category="Alice-Only", monthly_limit_cents=10_000)
        _make_budget(db_session, user_b.id, category="Bob-Only", monthly_limit_cents=20_000)
        db_session.commit()

        snap_a = _build(db_session, user_a.id)
        snap_b = _build(db_session, user_b.id)

        # Balances are per-user, not shared
        assert snap_a["cashflow_forecast"]["starting_balance"] == 1000.0
        assert snap_b["cashflow_forecast"]["starting_balance"] == 9990.0

        # Budget categories don't cross users
        cats_a = {c["category"] for c in snap_a["budgets"]["categories"]}
        cats_b = {c["category"] for c in snap_b["budgets"]["categories"]}
        assert "Bob-Only" not in cats_a
        assert "Alice-Only" not in cats_b


# ---------------------------------------------------------------------------
# Compose-by-scope (hardening)
# ---------------------------------------------------------------------------

class TestComposeByScope:
    def test_scopes_none_includes_every_section(self, db_session):
        """Backward compat: build(uid) with no scopes returns full data (used by
        all the other context tests and the internal full snapshot)."""
        uid = _make_user(db_session).id
        s = ContextBuilder(db_session).build(uid)  # no scopes
        for section in ("spendable", "cashflow_forecast", "budgets", "goals"):
            assert "available" not in s[section], f"{section} unexpectedly stubbed"

    def test_each_section_gated_by_its_scope(self, db_session):
        uid = _make_user(db_session).id
        s = ContextBuilder(db_session).build(
            uid, scopes=frozenset(["read:accounts"])
        )
        # Only cashflow_forecast maps to read:accounts.
        assert "available" not in s["cashflow_forecast"]
        assert s["spendable"] == {"available": False, "required_scope": "read:budgets"}
        assert s["budgets"] == {"available": False, "required_scope": "read:budgets"}
        assert s["goals"] == {"available": False, "required_scope": "read:goals"}

    def test_empty_scopes_stubs_everything(self, db_session):
        uid = _make_user(db_session).id
        s = ContextBuilder(db_session).build(uid, scopes=frozenset())
        for section in ("spendable", "cashflow_forecast", "budgets", "goals"):
            assert s[section]["available"] is False
