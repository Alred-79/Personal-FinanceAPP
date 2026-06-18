"""W5 — Freelancer onboarding preset.

Covers: the preset creates exactly ONE Tax Reserve goal + ONE allocate rule; it is
idempotent (a re-run creates nothing new, refreshes in place); it no-ops the tax
steps gracefully when tax features are disabled; the effective reserve pct derives
from the tax estimate; the reserve allocate rule fires on self_employment income
ONLY (never on a W-2 paycheck or an expense) and earmarks the Tax Reserve goal.
"""

from __future__ import annotations

import json

import pytest

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    Rule as RuleORM,
    User as UserORM,
)
from server.src.services.freelancer_setup import (
    TAX_RESERVE_GOAL_NAME,
    TAX_RESERVE_RULE_NAME,
    run_preset,
)
from server.src.services.rule_engine import RuleEngine
from server.src.settings import settings


@pytest.fixture
def tax_on(monkeypatch):
    monkeypatch.setattr(settings, "tax_features_enabled", True)
    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", False)
    yield


def _user(db, username="freel"):
    u = UserORM(username=username, full_name="F", email=f"{username}@e.com",
                hashed_password="x")
    db.add(u)
    db.flush()
    return u


def _account(db, uid):
    a = AccountORM(name="Checking", type="depository", balance=0, user_id=uid)
    db.add(a)
    db.flush()
    return a


def _income(db, acct_id, title, cents, date, source_type=None):
    i = IncomeORM(title=title, amount=cents, date=date, category="Work",
                  account_id=acct_id, source_type=source_type)
    db.add(i)
    db.flush()
    return i


def _count_goals(db, uid):
    return (
        db.query(GoalORM)
        .filter(GoalORM.user_id == uid, GoalORM.name == TAX_RESERVE_GOAL_NAME)
        .count()
    )


def _count_rules(db, uid):
    return (
        db.query(RuleORM)
        .filter(RuleORM.user_id == uid, RuleORM.name == TAX_RESERVE_RULE_NAME)
        .count()
    )


# ── core preset ──────────────────────────────────────────────────────────────

class TestPreset:
    def test_creates_exactly_one_goal_and_rule(self, db_session, tax_on):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        # Some self-employment income so the estimate has a non-zero pct.
        _income(db, a.id, "Client 1099", 5000000, "2026-02-01", "self_employment")

        result = run_preset(db, u.id, tax_year=2026)
        assert result.created_goal is True
        assert result.created_rule is True
        assert result.tax_steps_applied is True
        assert _count_goals(db, u.id) == 1
        assert _count_rules(db, u.id) == 1
        # Horizon set; smoothing returned (not applied).
        assert result.s2s_horizon == "month"
        assert u.s2s_buffer == 0  # never auto-applied (B2)

    def test_rule_conditions_require_income_and_self_employment(self, db_session, tax_on):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        _income(db, a.id, "Client 1099", 5000000, "2026-02-01", "self_employment")
        run_preset(db, u.id, tax_year=2026)
        rule = (
            db.query(RuleORM)
            .filter(RuleORM.user_id == u.id, RuleORM.name == TAX_RESERVE_RULE_NAME)
            .one()
        )
        conds = json.loads(rule.conditions)
        # MUST require both the income type and self_employment source — so it can
        # never match an expense or a W-2 paycheck.
        assert {"field": "type", "op": "eq", "value": "income"} in conds
        assert {
            "field": "source_type", "op": "eq", "value": "self_employment",
        } in conds
        assert rule.action_type == "allocate"
        assert rule.target_kind == "goal"
        # pct present and in range.
        params = json.loads(rule.action_params)
        assert 0 <= params["pct"] <= 100

    def test_reserve_pct_derives_from_estimate(self, db_session, tax_on):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        _income(db, a.id, "Client 1099", 8000000, "2026-02-01", "self_employment")
        result = run_preset(db, u.id, tax_year=2026)
        # Effective pct == annual_estimate / total_income, > 0 on real income.
        assert result.reserve_pct is not None and result.reserve_pct > 0
        assert result.reserve_target_cents is not None and result.reserve_target_cents > 0

    def test_idempotent_rerun_creates_nothing_new(self, db_session, tax_on):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        _income(db, a.id, "Client 1099", 5000000, "2026-02-01", "self_employment")
        r1 = run_preset(db, u.id, tax_year=2026)
        r2 = run_preset(db, u.id, tax_year=2026)
        assert r2.created_goal is False
        assert r2.created_rule is False
        assert r2.goal_id == r1.goal_id
        assert r2.rule_id == r1.rule_id
        assert _count_goals(db, u.id) == 1
        assert _count_rules(db, u.id) == 1

    def test_no_ops_tax_steps_when_disabled(self, db_session, monkeypatch):
        db = db_session
        monkeypatch.setattr(settings, "tax_features_enabled", False)
        monkeypatch.setattr(settings, "merchant_lifecycle_enabled", False)
        u = _user(db)
        a = _account(db, u.id)
        _income(db, a.id, "Client 1099", 5000000, "2026-02-01", "self_employment")
        # enable_tax_features=False AND flag off → tax steps skip gracefully.
        result = run_preset(db, u.id, tax_year=2026, enable_tax_features=False)
        assert result.tax_steps_applied is False
        assert result.goal_id is None
        assert result.rule_id is None
        assert _count_goals(db, u.id) == 0
        assert _count_rules(db, u.id) == 0
        # The non-tax steps still ran.
        assert result.s2s_horizon == "month"
        assert result.smoothing is not None


# ── the reserve rule fires on self_employment income ONLY ────────────────────

class TestReserveRuleFiring:
    def _setup(self, db, tax_on):
        u = _user(db)
        a = _account(db, u.id)
        # Build the reserve rule + goal via the preset (income so pct > 0).
        _income(db, a.id, "Seed 1099", 5000000, "2026-01-01", "self_employment")
        run_preset(db, u.id, tax_year=2026)
        goal = (
            db.query(GoalORM)
            .filter(GoalORM.user_id == u.id, GoalORM.name == TAX_RESERVE_GOAL_NAME)
            .one()
        )
        return u, a, goal

    def test_fires_on_self_employment_income(self, db_session, tax_on):
        db = db_session
        u, a, goal = self._setup(db, tax_on)
        before = goal.progress or 0
        # A small self_employment income row → pct*amount stays under the $100
        # auto-execute threshold, so it earmarks silently (vs proposing). $200 *
        # ~30% = ~$60 ≤ $100.
        inc = _income(db, a.id, "New client", 20000, "2026-03-01", "self_employment")
        RuleEngine(db).run_on_transaction(
            u.id, "income", inc.id,
            {"id": inc.id, "title": inc.title, "amount": 200.0,
             "date": inc.date, "category": "Work", "account_id": a.id,
             "type": "income", "source_type": "self_employment"},
        )
        db.refresh(goal)
        assert (goal.progress or 0) > before  # reserve funded

    def test_does_not_fire_on_w2_income(self, db_session, tax_on):
        db = db_session
        u, a, goal = self._setup(db, tax_on)
        before = goal.progress or 0
        inc = _income(db, a.id, "ACME PAYROLL", 100000, "2026-03-02", "w2")
        RuleEngine(db).run_on_transaction(
            u.id, "income", inc.id,
            {"id": inc.id, "title": inc.title, "amount": 1000.0,
             "date": inc.date, "category": "Work", "account_id": a.id,
             "type": "income", "source_type": "w2"},
        )
        db.refresh(goal)
        assert (goal.progress or 0) == before  # untouched — W-2 is not reserved

    def test_does_not_fire_on_expense(self, db_session, tax_on):
        db = db_session
        u, a, goal = self._setup(db, tax_on)
        before = goal.progress or 0
        exp = ExpenseORM(title="Office chair", amount=20000, date="2026-03-03",
                         category="Shops", account_id=a.id)
        db.add(exp)
        db.flush()
        RuleEngine(db).run_on_transaction(
            u.id, "expense", exp.id,
            {"id": exp.id, "title": exp.title, "amount": 200.0,
             "date": exp.date, "category": "Shops", "account_id": a.id,
             "type": "expense"},  # no source_type on an expense
        )
        db.refresh(goal)
        assert (goal.progress or 0) == before  # untouched — never matches a spend
