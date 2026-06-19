"""Rules engine tests (v1 Layer B + the v2 categorize action).

Covers: each action type, condition matching, idempotency (same tx twice fires
once), priority ordering, round-up math, the creation-path hook, the earmark
effect on Safe-to-Spend, and the API CRUD/preview surface.
"""

import json
from datetime import date

import pytest

from .conftest import wire_plaid_pages  # L5: bridge sync_transactions → pages
from server.src.db.models import (
    Account,
    Expense,
    Goal,
    Notification,
    Rule,
    RuleExecution,
    User,
)
from server.src.services.rule_engine import RuleEngine, matches, roundup_cents


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestRoundupMath:
    def test_nearest_dollar(self):
        assert roundup_cents(450, 100) == 50
        assert roundup_cents(401, 100) == 99
        assert roundup_cents(400, 100) == 0  # exact multiple → nothing

    def test_nearest_five(self):
        assert roundup_cents(450, 500) == 50
        assert roundup_cents(1, 500) == 499


class TestConditions:
    TX = {
        "id": 1,
        "title": "Starbucks Coffee",
        "amount": 4.50,
        "category": "Food",
        "account_id": 7,
        "type": "expense",
    }

    def test_empty_matches_all(self):
        assert matches([], self.TX) is True

    def test_category_eq_and_in(self):
        assert matches([{"field": "category", "op": "eq", "value": "food"}], self.TX)
        assert matches(
            [{"field": "category", "op": "in", "value": ["Travel", "Food"]}], self.TX
        )
        assert not matches(
            [{"field": "category", "op": "eq", "value": "Travel"}], self.TX
        )

    def test_amount_thresholds(self):
        assert matches([{"field": "amount", "op": "gt", "value": 4}], self.TX)
        assert matches([{"field": "amount", "op": "lt", "value": 5}], self.TX)
        assert not matches([{"field": "amount", "op": "gt", "value": 10}], self.TX)

    def test_title_contains(self):
        assert matches(
            [{"field": "title", "op": "contains", "value": "starbucks"}], self.TX
        )

    def test_all_of_semantics(self):
        conds = [
            {"field": "category", "op": "eq", "value": "Food"},
            {"field": "amount", "op": "gt", "value": 100},
        ]
        assert not matches(conds, self.TX)

    def test_unknown_field_or_op_fails_closed(self):
        assert not matches([{"field": "merchant", "op": "eq", "value": "x"}], self.TX)
        assert not matches([{"field": "amount", "op": "between", "value": 1}], self.TX)

    def test_source_type_match(self):
        """W5: source_type == self_employment matches a 1099 income tx ONLY."""
        se = {"type": "income", "source_type": "self_employment", "amount": 100.0}
        w2 = {"type": "income", "source_type": "w2", "amount": 100.0}
        cond = [{"field": "source_type", "op": "eq", "value": "self_employment"}]
        assert matches(cond, se)
        assert not matches(cond, w2)
        # Absent on an expense / unclassified income → fails closed (no match).
        assert not matches(cond, self.TX)
        assert not matches(cond, {"type": "income", "amount": 100.0})


# ---------------------------------------------------------------------------
# Engine over the DB
# ---------------------------------------------------------------------------

@pytest.fixture
def rule_user(db_session):
    user = User(
        username="rule_user",
        full_name="Rule User",
        email="rule@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    account = Account(name="Checking", type="checking", balance=100_000, user_id=user.id)
    goal = Goal(
        name="Vault", amount=50_000, date="2027-01-01", user_id=user.id, progress=0
    )
    db_session.add_all([account, goal])
    db_session.flush()
    return user, account, goal


def _mk_rule(db_session, user, action_type, params=None, conditions=None, goal=None, priority=0, name="r"):
    rule = Rule(
        user_id=user.id,
        name=name,
        enabled=1,
        conditions=json.dumps(conditions or []),
        action_type=action_type,
        action_params=json.dumps(params or {}),
        target_kind="goal" if goal is not None else None,
        target_id=goal.id if goal is not None else None,
        priority=priority,
    )
    db_session.add(rule)
    db_session.flush()
    return rule


TX = lambda **kw: {  # noqa: E731
    "id": kw.get("id", 1),
    "title": kw.get("title", "Latte"),
    "amount": kw.get("amount", 4.50),
    "date": "2026-03-10",
    "category": kw.get("category", "Food"),
    "account_id": kw.get("account_id", 1),
    "type": kw.get("type", "expense"),
}


class TestActions:
    def test_roundup_funds_goal(self, db_session, rule_user):
        user, _, goal = rule_user
        _mk_rule(db_session, user, "roundup", {"nearest": "1"}, goal=goal)
        execs = RuleEngine(db_session).run_on_transaction(user.id, "expense", 1, TX())
        assert len(execs) == 1
        assert execs[0].amount_cents == 50  # 4.50 → 5.00
        assert goal.progress == 50

    def test_allocate_fixed_and_pct(self, db_session, rule_user):
        user, _, goal = rule_user
        _mk_rule(db_session, user, "allocate", {"amount": 2.0}, goal=goal, name="fixed")
        _mk_rule(db_session, user, "allocate", {"pct": 10}, goal=goal, name="pct")
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "expense", 2, TX(id=2, amount=40.0)
        )
        assert sorted(e.amount_cents for e in execs) == [200, 400]
        assert goal.progress == 600

    def test_allocate_completes_goal(self, db_session, rule_user):
        user, _, goal = rule_user
        goal.progress = 49_900
        _mk_rule(db_session, user, "allocate", {"amount": 5.0}, goal=goal)
        RuleEngine(db_session).run_on_transaction(user.id, "expense", 3, TX(id=3))
        assert goal.progress >= goal.amount
        assert goal.completed == 1

    def test_notify_writes_notification(self, db_session, rule_user):
        user, _, _ = rule_user
        _mk_rule(
            db_session,
            user,
            "notify",
            {"message": "big spend!"},
            conditions=[{"field": "amount", "op": "gt", "value": 100}],
        )
        RuleEngine(db_session).run_on_transaction(
            user.id, "expense", 4, TX(id=4, amount=250.0)
        )
        notes = db_session.query(Notification).filter_by(user_id=user.id).all()
        assert len(notes) == 1
        assert notes[0].type == "rule"
        assert notes[0].message == "big spend!"

    def test_categorize_recategorizes_expense(self, db_session, rule_user):
        """v2: user-editable categorization rule."""
        user, account, _ = rule_user
        row = Expense(
            title="UBER TRIP 123",
            amount=1_550,
            date="2026-03-10",
            category="Other",
            account_id=account.id,
        )
        db_session.add(row)
        db_session.flush()
        _mk_rule(
            db_session,
            user,
            "categorize",
            {"category": "Transport"},
            conditions=[{"field": "title", "op": "contains", "value": "uber"}],
        )
        RuleEngine(db_session).run_on_transaction(
            user.id,
            "expense",
            row.id,
            TX(id=row.id, title=row.title, amount=15.50, category="Other"),
        )
        assert row.category == "Transport"

    def test_roundup_exact_amount_noop(self, db_session, rule_user):
        user, _, goal = rule_user
        _mk_rule(db_session, user, "roundup", {"nearest": "1"}, goal=goal)
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "expense", 5, TX(id=5, amount=5.00)
        )
        assert execs[0].result == "noop"
        assert goal.progress == 0


class TestIdempotencyAndOrdering:
    def test_same_tx_fires_once(self, db_session, rule_user):
        user, _, goal = rule_user
        _mk_rule(db_session, user, "roundup", {"nearest": "1"}, goal=goal)
        engine = RuleEngine(db_session)
        engine.run_on_transaction(user.id, "expense", 10, TX(id=10))
        engine.run_on_transaction(user.id, "expense", 10, TX(id=10))  # replay
        assert goal.progress == 50  # not 100
        assert db_session.query(RuleExecution).count() == 1

    def test_same_id_different_type_both_fire(self, db_session, rule_user):
        user, _, _ = rule_user
        _mk_rule(db_session, user, "notify", {})
        engine = RuleEngine(db_session)
        engine.run_on_transaction(user.id, "expense", 11, TX(id=11))
        engine.run_on_transaction(user.id, "income", 11, TX(id=11, type="income"))
        assert db_session.query(RuleExecution).count() == 2

    def test_priority_order_and_disabled_skipped(self, db_session, rule_user):
        user, _, goal = rule_user
        low = _mk_rule(db_session, user, "notify", {}, priority=1, name="low")
        high = _mk_rule(db_session, user, "notify", {}, priority=9, name="high")
        off = _mk_rule(db_session, user, "notify", {}, priority=99, name="off")
        off.enabled = 0
        db_session.flush()
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "expense", 12, TX(id=12)
        )
        assert [e.rule_id for e in execs] == [high.id, low.id]

    def test_pause_stops_firing_immediately(self, db_session, rule_user):
        """W9: pausing a rule (enabled=0) must stop it firing on the NEXT
        evaluation — no stale rule cache. The engine reads ``enabled == 1`` live
        from the DB on every transaction and is constructed per batch, so there is
        no firing cache to go stale; flipping ``enabled`` is the invalidation."""
        user, _, goal = rule_user
        rule = _mk_rule(db_session, user, "allocate", {"amount": 1.0}, goal=goal)

        # Fires while enabled.
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "expense", 30, TX(id=30)
        )
        assert len(execs) == 1
        assert goal.progress == 100

        # Pause it. The very next transaction must not fire — even reusing the
        # SAME engine instance (the only per-engine cache is the threshold lookup,
        # which does not gate firing).
        rule.enabled = 0
        db_session.flush()
        engine = RuleEngine(db_session)
        execs2 = engine.run_on_transaction(user.id, "expense", 31, TX(id=31))
        assert execs2 == []
        assert goal.progress == 100  # unchanged — the paused rule did nothing


class TestAutoExecuteThreshold:
    """Pillar 2B — the bounded auto-execute lane.

    An allocate firing at or below the user's ``auto_execute_threshold_cents``
    earmarks silently (today's behavior). Above it the engine does NOT mutate
    ``Goal.progress``; it logs a ``needs_confirmation`` RuleExecution and writes a
    durable ``rule_proposal`` Notification, and a re-sync of the same tx mints
    exactly one pending proposal (the ``uq_rule_exec_tx`` row is the dedup key).
    No real money moves either way — the threshold only gates silent-vs-propose.
    """

    def _set_threshold(self, db_session, user, cents):
        user.auto_execute_threshold_cents = cents
        db_session.flush()

    def test_below_threshold_earmarks_silently(self, db_session, rule_user):
        user, _, goal = rule_user
        self._set_threshold(db_session, user, 10000)  # $100
        _mk_rule(
            db_session, user, "allocate", {"amount": 50.0}, goal=goal,
            conditions=[{"field": "type", "op": "eq", "value": "income"}],
        )
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "income", 20, TX(id=20, type="income", amount=2000.0)
        )
        assert len(execs) == 1
        assert execs[0].result == "ok"
        assert goal.progress == 5000  # $50 earmarked silently
        # No proposal notification for a below-threshold firing.
        assert (
            db_session.query(Notification)
            .filter_by(user_id=user.id, type="rule_proposal")
            .count()
            == 0
        )

    def test_above_threshold_proposes_not_earmarks(self, db_session, rule_user):
        user, _, goal = rule_user
        self._set_threshold(db_session, user, 10000)  # $100
        _mk_rule(
            db_session, user, "allocate", {"amount": 250.0}, goal=goal,
            conditions=[{"field": "type", "op": "eq", "value": "income"}],
        )
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "income", 21, TX(id=21, type="income", amount=5000.0)
        )
        assert len(execs) == 1
        assert execs[0].result == "needs_confirmation"
        assert execs[0].amount_cents == 25000  # logged, but...
        assert goal.progress == 0  # ...NOT applied — money didn't move
        notes = (
            db_session.query(Notification)
            .filter_by(user_id=user.id, type="rule_proposal")
            .all()
        )
        assert len(notes) == 1
        assert "$250.00" in notes[0].message
        assert notes[0].ref == f"rule_proposal:{execs[0].rule_id}:{goal.id}:25000"

    def test_resync_mints_exactly_one_pending_proposal(self, db_session, rule_user):
        """The uq_rule_exec_tx row dedups: syncing the same tx twice → one proposal."""
        user, _, goal = rule_user
        self._set_threshold(db_session, user, 10000)
        _mk_rule(
            db_session, user, "allocate", {"amount": 250.0}, goal=goal,
            conditions=[{"field": "type", "op": "eq", "value": "income"}],
        )
        engine = RuleEngine(db_session)
        engine.run_on_transaction(user.id, "income", 22, TX(id=22, type="income", amount=5000.0))
        engine.run_on_transaction(user.id, "income", 22, TX(id=22, type="income", amount=5000.0))  # re-sync
        assert (
            db_session.query(RuleExecution)
            .filter_by(result="needs_confirmation")
            .count()
            == 1
        )
        assert (
            db_session.query(Notification)
            .filter_by(user_id=user.id, type="rule_proposal")
            .count()
            == 1
        )
        assert goal.progress == 0

    def test_at_threshold_boundary_earmarks(self, db_session, rule_user):
        """Exactly == threshold is auto (≤ is the rule); just-over proposes."""
        user, _, goal = rule_user
        self._set_threshold(db_session, user, 10000)  # $100
        _mk_rule(
            db_session, user, "allocate", {"amount": 100.0}, goal=goal,
            conditions=[{"field": "type", "op": "eq", "value": "income"}],
        )
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "income", 23, TX(id=23, type="income", amount=3000.0)
        )
        assert execs[0].result == "ok"
        assert goal.progress == 10000  # exactly at the limit → still auto

    def test_just_over_threshold_proposes(self, db_session, rule_user):
        user, _, goal = rule_user
        self._set_threshold(db_session, user, 10000)
        _mk_rule(
            db_session, user, "allocate", {"amount": 100.01}, goal=goal,
            conditions=[{"field": "type", "op": "eq", "value": "income"}],
        )
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "income", 24, TX(id=24, type="income", amount=3000.0)
        )
        assert execs[0].result == "needs_confirmation"
        assert goal.progress == 0

    def test_two_txns_same_rule_amount_dont_stack_notifications(self, db_session, rule_user):
        """Two DIFFERENT income txns trip the same above-threshold rule for the
        same amount → one proposal notification, not two (check-before-add)."""
        user, _, goal = rule_user
        self._set_threshold(db_session, user, 10000)
        _mk_rule(
            db_session, user, "allocate", {"amount": 250.0}, goal=goal,
            conditions=[{"field": "type", "op": "eq", "value": "income"}],
        )
        engine = RuleEngine(db_session)
        engine.run_on_transaction(user.id, "income", 30, TX(id=30, type="income", amount=5000.0))
        engine.run_on_transaction(user.id, "income", 31, TX(id=31, type="income", amount=6000.0))
        # Two distinct firings (different tx ids) → two RuleExecution rows...
        assert (
            db_session.query(RuleExecution)
            .filter_by(result="needs_confirmation")
            .count()
            == 2
        )
        # ...but one de-duplicated proposal notification (same rule + goal + amount).
        assert (
            db_session.query(Notification)
            .filter_by(user_id=user.id, type="rule_proposal")
            .count()
            == 1
        )


class TestCreationHookAndEarmarks:
    """End-to-end through the API: the single creation path runs the engine."""

    def _setup(self, client):
        resp = client.post(
            "/api/signup/",
            json={
                "username": "rulehook",
                "email": "rulehook@example.com",
                "full_name": "Rule Hook",
                "password": "Test-password1",
            },
        )
        assert resp.status_code == 200, resp.text
        headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        client.cookies.clear()
        client.post(
            "/api/accounts/",
            json={"name": "Checking", "type": "checking", "balance": 1000.0},
            headers=headers,
        )
        acct = client.get("/api/accounts/", headers=headers).json()[-1]["id"]
        client.post(
            "/api/goals/",
            json={"name": "Vault", "amount": 500.0, "date": "2027-01-01"},
            headers=headers,
        )
        goal = client.get("/api/goals/", headers=headers).json()[-1]
        return headers, acct, goal

    def test_roundup_via_api_and_safe_to_spend_drops(self, client):
        headers, acct, goal = self._setup(client)

        resp = client.post(
            "/api/rules/",
            json={
                "name": "Round up purchases",
                "action_type": "roundup",
                "action_params": {"nearest": "1"},
                "target_kind": "goal",
                "target_id": goal["id"],
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        before = client.get("/api/spend/safe-to-spend/", headers=headers).json()

        resp = client.post(
            "/api/expenses/",
            json={
                "account_id": acct,
                "title": "Latte",
                "amount": 4.25,
                "date": "2026-03-10",
                "category": "Food",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        goal_after = client.get("/api/goals/", headers=headers).json()[-1]
        assert goal_after["progress"] == 0.75  # 4.25 → 5.00

        # Earmark wiring: the balance drops by the expense and the earmark
        # bites on top of it. (The goal-contribution component shrinks a hair
        # as progress rises, so the total drop sits between the expense alone
        # and expense + earmark.)
        after = client.get("/api/spend/safe-to-spend/", headers=headers).json()
        assert after["breakdown"]["goal_earmarks"] == 0.75
        assert (
            after["breakdown"]["current_balance"]
            == before["breakdown"]["current_balance"] - 4.25
        )
        drop = round(before["available"] - after["available"], 2)
        assert 4.25 < drop <= 5.00

    def test_rule_crud_validation_and_preview(self, client):
        headers, acct, goal = self._setup(client)

        # allocate without a target → 422
        resp = client.post(
            "/api/rules/",
            json={"name": "bad", "action_type": "allocate", "action_params": {"amount": 1}},
            headers=headers,
        )
        assert resp.status_code == 422

        # unknown action type → 422
        resp = client.post(
            "/api/rules/",
            json={"name": "bad", "action_type": "teleport"},
            headers=headers,
        )
        assert resp.status_code == 422

        # someone else's goal → 404
        resp = client.post(
            "/api/rules/",
            json={
                "name": "bad",
                "action_type": "allocate",
                "action_params": {"amount": 1},
                "target_kind": "goal",
                "target_id": goal["id"] + 999,
            },
            headers=headers,
        )
        assert resp.status_code == 404

        # preview is a dry run: reports the sweep, writes nothing
        resp = client.post(
            "/api/rules/preview/",
            json={
                "action_type": "roundup",
                "action_params": {"nearest": "5"},
                "conditions": [{"field": "category", "op": "eq", "value": "Food"}],
                "sample_txns": [
                    {"id": 1, "title": "Latte", "amount": 4.50, "category": "Food", "type": "expense"},
                    {"id": 2, "title": "Gas", "amount": 30.0, "category": "Transport", "type": "expense"},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        preview = resp.json()
        assert len(preview) == 1  # only the Food txn matches
        assert preview[0]["amount"] == 0.50
        assert client.get("/api/goals/", headers=headers).json()[-1]["progress"] == 0


# ---------------------------------------------------------------------------
# Step 08: rules fire on Plaid-synced transactions (not just manual entry)
# ---------------------------------------------------------------------------

class TestRulesFireOnSync:
    def test_rule_fires_on_synced_transaction(self, db_session, rule_user):
        """A roundup rule that fires on a manual txn also fires on a synced one.

        Closes the report finding that ``sync_token`` never called the rule
        engine (the in-code comment claimed it did). The synced expense funds the
        goal exactly as a manual entry would.
        """
        from unittest.mock import MagicMock, patch

        from server.src.db.models import Token as TokenORM
        from server.src.databridge.plaid_client import SyncResult
        from server.src.models import UserInDB
        from server.src.services.plaid_service import PlaidService

        user, account, goal = rule_user
        # An id-keyed Plaid account so sync routes by plaid_account_id.
        account.plaid_account_id = "acct_X"
        token = TokenORM(user_id=user.id, name="Bank", key="access-plain")
        db_session.add(token)
        db_session.flush()

        _mk_rule(db_session, user, "roundup", {"nearest": "1"}, goal=goal)

        user_in_db = UserInDB(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            disabled=False,
            hashed_password=user.hashed_password,
        )

        with patch("server.src.services.plaid_service.PlaidClient") as MockPDB:
            mock_plaid = MagicMock()
            MockPDB.return_value = wire_plaid_pages(mock_plaid)
            mock_plaid.get_balance.return_value = []
            mock_plaid.sync_transactions.return_value = SyncResult(
                added=[
                    {
                        "transaction_id": "synced_1",
                        "name": "Coffee",
                        "amount": 4.50,  # → rounds up 50¢ into the goal
                        "date": "2026-03-10",
                        "category": ["Food"],
                        "personal_finance_category": None,
                        "account_id": "acct_X",
                    }
                ],
                modified=[],
                removed=[],
                next_cursor="c1",
            )
            PlaidService(db_session).sync_all_tokens(user_in_db)
            db_session.flush()

        db_session.refresh(goal)
        assert goal.progress == 50  # the rule fired on the synced expense


# ---------------------------------------------------------------------------
# A2 — money-moving rules must not earmark income unless they opt in
# ---------------------------------------------------------------------------

def INCOME_TX(**kw):
    """A synced-income tx view (mirrors plaid_service `_run_rules_on_synced`):
    ``type`` always set, ``source_type`` only when classified."""
    tx = {
        "id": kw.get("id", 1),
        "title": kw.get("title", "Paycheck"),
        "amount": kw.get("amount", 1000.0),
        "date": "2026-03-10",
        "category": kw.get("category", "Work"),
        "account_id": kw.get("account_id", 1),
        "type": "income",
    }
    if "source_type" in kw:
        tx["source_type"] = kw["source_type"]
    return tx


class TestIncomeEarmarkGuard:
    def test_roundup_empty_conditions_does_not_fire_on_income(
        self, db_session, rule_user
    ):
        """A roundup rule with NO conditions is match-all; on a paycheck/refund it
        must NOT siphon money. It records a skip (no money moved) instead."""
        user, _, goal = rule_user
        _mk_rule(db_session, user, "roundup", {"nearest": "1"}, goal=goal)
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "income", 1, INCOME_TX(amount=1000.0)
        )
        assert len(execs) == 1
        assert execs[0].amount_cents == 0  # moved nothing
        assert execs[0].result == "skip_non_expense"
        db_session.refresh(goal)
        assert goal.progress == 0

    def test_allocate_empty_conditions_does_not_fire_on_income(
        self, db_session, rule_user
    ):
        user, _, goal = rule_user
        _mk_rule(db_session, user, "allocate", {"pct": 10}, goal=goal)
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "income", 2, INCOME_TX(id=2, amount=1000.0)
        )
        assert len(execs) == 1
        assert execs[0].amount_cents == 0
        assert execs[0].result == "skip_non_expense"
        db_session.refresh(goal)
        assert goal.progress == 0

    def test_allocate_with_source_type_condition_still_fires_on_income(
        self, db_session, rule_user
    ):
        """W5's Tax-Reserve rule opts in via a ``source_type`` predicate, so it
        MUST still earmark self-employment income. Must not be blanket-blocked.

        Uses a $50 fixed allocation (≤ the $100 Pillar-2B auto-execute threshold)
        so the earmark funds immediately rather than surfacing a proposal."""
        user, _, goal = rule_user
        _mk_rule(
            db_session,
            user,
            "allocate",
            {"amount": 50.0},
            conditions=[
                {"field": "type", "op": "eq", "value": "income"},
                {"field": "source_type", "op": "eq", "value": "self_employment"},
            ],
            goal=goal,
        )
        execs = RuleEngine(db_session).run_on_transaction(
            user.id,
            "income",
            3,
            INCOME_TX(id=3, amount=1000.0, source_type="self_employment"),
        )
        assert len(execs) == 1
        # The rule fired (not skipped) and earmarked $50 — proves income opt-in.
        assert execs[0].amount_cents == 5_000
        assert execs[0].result != "skip_non_expense"
        db_session.refresh(goal)
        assert goal.progress == 5_000

    def test_guard_does_not_touch_expense_path(self, db_session, rule_user):
        """The guard only gates non-expense txns; ordinary expense roundup is
        unchanged."""
        user, _, goal = rule_user
        _mk_rule(db_session, user, "roundup", {"nearest": "1"}, goal=goal)
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "expense", 4, TX(id=4, amount=4.50)
        )
        assert execs[0].amount_cents == 50  # fired normally


class TestAllocationRounding:
    def test_pct_uses_bankers_rounding_not_truncation(self, db_session, rule_user):
        """A5: the pct path rounds (banker's) at the money seam instead of
        truncating toward zero. 0.5% of $13.33 = 6.665¢ → 6¢ (ties-to-even down),
        whereas a naive int() of 6.665 would ALSO give 6 — so pick a case where
        they differ: 1% of $13.50 = 13.5¢ → 14¢ (ties to even), int()=13."""
        user, _, goal = rule_user
        _mk_rule(db_session, user, "allocate", {"pct": 1}, goal=goal)
        execs = RuleEngine(db_session).run_on_transaction(
            user.id, "expense", 9, TX(id=9, amount=13.50)
        )
        # tx_amount_cents = 1350; 1350 * 1 / 100 = 13.5 → round_half_even → 14.
        assert execs[0].amount_cents == 14

    def test_synced_rule_is_idempotent_on_resync(self, db_session, rule_user):
        """Re-syncing the same txn id doesn't double-fire the rule (one row,
        one firing) — relies on the rule_executions unique key + the partial
        unique index."""
        from unittest.mock import MagicMock, patch

        from server.src.db.models import (
            RuleExecution as RuleExecutionORM,
            Token as TokenORM,
        )
        from server.src.databridge.plaid_client import SyncResult
        from server.src.models import UserInDB
        from server.src.services.plaid_service import PlaidService

        user, account, goal = rule_user
        account.plaid_account_id = "acct_Y"
        db_session.add(TokenORM(user_id=user.id, name="Bank", key="access-plain"))
        db_session.flush()
        _mk_rule(db_session, user, "roundup", {"nearest": "1"}, goal=goal)

        user_in_db = UserInDB(
            id=user.id, username=user.username, email=user.email,
            full_name=user.full_name, disabled=False,
            hashed_password=user.hashed_password,
        )
        txn = {
            "transaction_id": "synced_dup",
            "name": "Coffee",
            "amount": 4.50,
            "date": "2026-03-10",
            "category": ["Food"],
            "personal_finance_category": None,
            "account_id": "acct_Y",
        }

        with patch("server.src.services.plaid_service.PlaidClient") as MockPDB:
            mock_plaid = MagicMock()
            MockPDB.return_value = wire_plaid_pages(mock_plaid)
            mock_plaid.get_balance.return_value = []
            mock_plaid.sync_transactions.return_value = SyncResult(
                added=[txn], modified=[], removed=[], next_cursor="c1",
            )
            PlaidService(db_session).sync_all_tokens(user_in_db)
            db_session.flush()
            # Re-present the same id (cursor replay).
            mock_plaid.sync_transactions.return_value = SyncResult(
                added=[txn], modified=[], removed=[], next_cursor="c2",
            )
            PlaidService(db_session).sync_all_tokens(user_in_db)
            db_session.flush()

        db_session.refresh(goal)
        assert goal.progress == 50  # not 100
        assert db_session.query(RuleExecutionORM).count() == 1
