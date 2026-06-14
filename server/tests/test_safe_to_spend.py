"""Safe-to-Spend tests (v1 Feature 3).

The number is dynamic (recomputed per call) and anchored (default horizon =
next projected paycheck). Components are config-gated per user; earmarks
(Goal.progress) reduce it; daily_plan = available / days_remaining.

Service-level tests pin ``as_of`` so the horizon math is deterministic.
"""

import random
from datetime import date

import pytest

from server.src.db.models import Account, Expense, Goal, Income, User
from server.src.models import UserInDB
from server.src.services.scenario_overlay import (
    GoalMutation,
    ScenarioOverlay,
)
from server.src.services.spend_service import SpendService


@pytest.fixture
def s2s_user(db_session):
    user = User(
        username="s2s_user",
        full_name="S2S User",
        email="s2s@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    account = Account(
        name="Checking", type="checking", balance=100_000, user_id=user.id
    )  # $1,000
    db_session.add(account)
    db_session.flush()
    return user, account


def _as_user_in_db(user: User) -> UserInDB:
    return UserInDB(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=False,
        spend_warning=user.spend_warning or 20,
        savings_percent=user.savings_percent or 10,
        hashed_password="x",
    )


AS_OF = date(2026, 3, 10)


def _seed_paycheck(db_session, account, anchor="2026-03-01", amount=200_000):
    db_session.add(
        Income(
            title="Paycheck",
            amount=amount,  # $2,000
            date=anchor,
            category="Work",
            recurrence="bi-weekly",
            account_id=account.id,
        )
    )
    db_session.flush()


class TestHorizon:
    def test_horizon_is_next_paycheck(self, db_session, s2s_user):
        user, account = s2s_user
        _seed_paycheck(db_session, account)  # paydays 3/15, 3/29 …
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-15"
        assert out["horizon_source"] == "paycheck"
        assert out["days_remaining"] == 5

    def test_no_paycheck_falls_back_to_end_of_month(self, db_session, s2s_user):
        user, _ = s2s_user
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-31"
        assert out["horizon_source"] == "month_fallback"

    def test_week_and_month_horizons(self, db_session, s2s_user):
        user, _ = s2s_user
        user.s2s_horizon = "week"
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-17"
        user.s2s_horizon = "month"
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-31"


class TestComponents:
    def test_bills_subtract_and_income_adds(self, db_session, s2s_user):
        user, account = s2s_user
        user.s2s_horizon = "month"  # fixed horizon → 3/31
        db_session.add(
            Expense(
                title="Rent",
                amount=40_000,  # $400 on 3/20
                date="2026-02-20",
                category="Housing",
                recurrence="monthly",
                account_id=account.id,
            )
        )
        _seed_paycheck(db_session, account)  # +$2,000 on 3/15 and 3/29

        svc = SpendService(db_session)
        out = svc.safe_to_spend(_as_user_in_db(user), AS_OF)
        # 1000 − 400 + 4000 = 4600
        assert out["breakdown"]["upcoming_bills"] == 400.0
        assert out["breakdown"]["projected_income"] == 4000.0
        assert out["available"] == 4600.0

        # Toggle income off → 1000 − 400 = 600
        user.s2s_include_income = 0
        db_session.flush()
        out = svc.safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["projected_income"] == 0.0
        assert out["available"] == 600.0

    def test_earmarks_reduce_available(self, db_session, s2s_user):
        user, _ = s2s_user
        user.s2s_horizon = "month"
        db_session.add(
            Goal(
                name="Japan trip",
                amount=100_000,
                date="2027-01-01",
                user_id=user.id,
                progress=25_000,  # $250 earmarked
            )
        )
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["goal_earmarks"] == 250.0
        # Contributions also subtract (a positive number over the horizon).
        assert out["breakdown"]["goal_contributions"] > 0
        assert out["available"] < 1000.0 - 250.0

        # Toggle goals off → plain balance.
        user.s2s_include_goals = 0
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["goal_earmarks"] == 0.0
        assert out["available"] == 1000.0

    def test_probabilistic_fields_are_additive(self, db_session, s2s_user):
        """Safe-to-spend gains overdraft_probability + trough_band without
        touching the existing available/daily_plan/breakdown values."""
        user, _ = s2s_user
        user.s2s_horizon = "month"
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(
            _as_user_in_db(user), AS_OF, rng=random.Random(0)
        )
        # New fields present and well-formed.
        assert 0.0 <= out["overdraft_probability"] <= 1.0
        band = out["trough_band"]
        assert band["low"] <= band["median"] <= band["high"]
        # Existing contract untouched: plain $1,000 balance, no bills/income/goals.
        assert out["available"] == 1000.0
        assert out["breakdown"]["current_balance"] == 1000.0

    def test_buffer_subtracts(self, db_session, s2s_user):
        user, _ = s2s_user
        user.s2s_horizon = "month"
        user.s2s_buffer = 10_000  # $100
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["buffer"] == 100.0
        assert out["available"] == 900.0

    def test_goal_contribution_uses_bankers_rounding(self, db_session, s2s_user):
        """The per-horizon goal contribution rounds fractional cents the same way
        as the rest of the money layer (ROUND_HALF_EVEN), not int() truncation.

        amount=$100, progress=0, deadline 3/23 → days_to_goal=13; horizon=month →
        days_remaining=21. daily = 10000/13 = 769.23…; daily*21 = 16153.846…,
        which truncates to 16153 but banker-rounds to 16154 ($161.54)."""
        user, _ = s2s_user
        user.s2s_horizon = "month"  # fixed horizon end 3/31 → days_remaining 21
        db_session.add(
            Goal(
                name="Fractional",
                amount=10_000,  # $100
                date="2026-03-23",
                user_id=user.id,
                progress=0,
            )
        )
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        # $161.54, the banker's-rounded contribution (truncation would give 161.53).
        assert out["breakdown"]["goal_contributions"] == 161.54

    def test_daily_plan_is_available_over_days(self, db_session, s2s_user):
        user, account = s2s_user
        _seed_paycheck(db_session, account)  # horizon 3/15, 5 days out
        user.s2s_include_income = 0
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["days_remaining"] == 5
        assert out["daily_plan"] == out["available"] / 5

    def test_safe_to_spend_excludes_anchor_paycheck(self, db_session, s2s_user):
        """Step 06: with the default (paycheck) horizon, the paycheck that lands
        EXACTLY on the horizon boundary (``next_pay``) must NOT be counted as
        income for this horizon. ``project_cashflows`` has an inclusive upper
        bound, so without the fix the anchor paycheck inflated spendable by a full
        pay period."""
        user, account = s2s_user  # balance = $1,000, include_income default on
        _seed_paycheck(db_session, account)  # bi-weekly from 3/1 → 3/15 is next_pay
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)

        # Horizon anchors on the 3/15 paycheck.
        assert out["horizon_end"] == "2026-03-15"
        assert out["horizon_source"] == "paycheck"
        # The boundary paycheck is excluded → no projected income within horizon.
        assert out["breakdown"]["projected_income"] == 0.0
        # Available is the plain balance (no phantom pay-period of income).
        assert out["available"] == 1000.0

    def test_only_anchor_paycheck_excluded_not_all_same_day_income(
        self, db_session, s2s_user
    ):
        """When TWO income streams land on the anchoring paycheck date, only the
        single anchoring paycheck is excluded — the second deposit still counts.

        Bug before the fix: ``item['date'] == horizon_end_iso`` dropped *all*
        boundary income, so a same-day second income vanished. Both streams here
        are $2,000, so the bug yields projected_income=$0 and the fix yields
        $2,000 (exactly one excluded), independent of emit order."""
        user, account = s2s_user
        _seed_paycheck(db_session, account)  # bi-weekly from 3/1 → anchors 3/15
        # A second recurring income (weekly from 3/8) also lands on 3/15.
        db_session.add(
            Income(
                title="Side gig",
                amount=200_000,  # $2,000, same as the paycheck
                date="2026-03-08",
                category="Work",
                recurrence="weekly",
                account_id=account.id,
            )
        )
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-15"
        # Exactly ONE $2,000 stream excluded; the other still counts.
        assert out["breakdown"]["projected_income"] == 2000.0

    def test_paycheck_strictly_inside_horizon_still_counts(self, db_session, s2s_user):
        """Sanity: a paycheck landing strictly BEFORE the horizon end is still
        income — only the boundary one is excluded. Use a fixed 'month' horizon so
        both 3/15 and 3/29 paychecks fall strictly inside 3/31."""
        user, account = s2s_user
        user.s2s_horizon = "month"  # horizon end 3/31 (not a paycheck date)
        db_session.flush()
        _seed_paycheck(db_session, account)  # 3/15 and 3/29, both < 3/31
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-31"
        # Both paychecks counted ($2,000 each).
        assert out["breakdown"]["projected_income"] == 4000.0


class TestEndpointAndSettings:
    def test_endpoint_and_gear_roundtrip(self, client):
        resp = client.post(
            "/api/signup/",
            json={
                "username": "s2sapi",
                "email": "s2sapi@example.com",
                "full_name": "S2S Api",
                "password": "Test-password1",
            },
        )
        assert resp.status_code == 200, resp.text
        headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        client.cookies.clear()
        client.post(
            "/api/accounts/",
            json={"name": "Checking", "type": "checking", "balance": 500.0},
            headers=headers,
        )

        resp = client.get("/api/spend/safe-to-spend/", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {"available", "horizon_end", "days_remaining", "daily_plan", "breakdown"} <= set(body)

        # The gear: change the rules behind the number.
        resp = client.put(
            "/api/settings/preferences/",
            json={"s2s_horizon": "week", "s2s_buffer": 50.0, "birth_year": 1999},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        prefs = resp.json()
        assert prefs["s2s_horizon"] == "week"
        assert prefs["s2s_buffer"] == 50.0
        assert prefs["birth_year"] == 1999

        body2 = client.get("/api/spend/safe-to-spend/", headers=headers).json()
        assert body2["config"]["horizon"] == "week"
        assert body2["available"] == body["available"] - 50.0  # buffer bites

        # Invalid horizon rejected.
        resp = client.put(
            "/api/settings/preferences/",
            json={"s2s_horizon": "fortnight"},
            headers=headers,
        )
        assert resp.status_code == 422


class TestOverlay:
    """Scenario overlay threading through safe_to_spend (v6 doc 02). R1: an
    omitted / empty overlay changes nothing; populated overlays reshape the
    number without writing to the DB."""

    def test_overlay_none_is_identical(self, db_session, s2s_user):
        user, account = s2s_user
        user.s2s_horizon = "month"
        db_session.add(
            Expense(
                title="Rent", amount=40_000, date="2026-02-20",
                category="Housing", recurrence="monthly", account_id=account.id,
            )
        )
        _seed_paycheck(db_session, account)
        db_session.add(
            Goal(name="Trip", amount=100_000, date="2027-01-01",
                 user_id=user.id, progress=25_000)
        )
        db_session.flush()
        svc = SpendService(db_session)
        plain = svc.safe_to_spend(
            _as_user_in_db(user), AS_OF, rng=random.Random(0)
        )
        empty = svc.safe_to_spend(
            _as_user_in_db(user), AS_OF, rng=random.Random(0),
            overlay=ScenarioOverlay(),
        )
        assert plain == empty

    def test_config_overrides_flip_income_and_buffer(self, db_session, s2s_user):
        """``config_overrides`` layer over the stored s2s_* rules: flip income
        off and add a buffer without touching the DB row."""
        user, account = s2s_user
        user.s2s_horizon = "month"  # 3/31
        _seed_paycheck(db_session, account)  # +$2,000 on 3/15 and 3/29
        db_session.flush()
        svc = SpendService(db_session)

        # Baseline: income on, no buffer → 1000 + 4000 = 5000.
        base = svc.safe_to_spend(_as_user_in_db(user), AS_OF)
        assert base["breakdown"]["projected_income"] == 4000.0
        assert base["available"] == 5000.0

        out = svc.safe_to_spend(
            _as_user_in_db(user), AS_OF,
            overlay=ScenarioOverlay(
                config_overrides={"s2s_include_income": 0, "s2s_buffer": 10_000},
            ),
        )
        # Income suppressed, $100 buffer bites → 1000 - 100 = 900.
        assert out["breakdown"]["projected_income"] == 0.0
        assert out["breakdown"]["buffer"] == 100.0
        assert out["available"] == 900.0
        # The stored config is untouched (hypothetical only).
        assert out["config"]["include_income"] is False
        assert user.s2s_include_income != 0

    def test_config_override_horizon_moves_window(self, db_session, s2s_user):
        """A ``s2s_horizon`` override changes the measured window."""
        user, _ = s2s_user  # default stored horizon is paycheck/fallback
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(
            _as_user_in_db(user), AS_OF,
            overlay=ScenarioOverlay(config_overrides={"s2s_horizon": "week"}),
        )
        assert out["horizon_end"] == "2026-03-17"
        assert out["config"]["horizon"] == "week"

    def test_goal_mutation_changes_earmarks_and_contributions(
        self, db_session, s2s_user
    ):
        """A ``goal_mutation`` reshapes a goal's progress (earmark) and amount
        (remaining contribution) hypothetically."""
        user, _ = s2s_user
        user.s2s_horizon = "month"
        goal = Goal(name="Japan", amount=100_000, date="2027-01-01",
                    user_id=user.id, progress=25_000)
        db_session.add(goal)
        db_session.flush()
        svc = SpendService(db_session)

        base = svc.safe_to_spend(_as_user_in_db(user), AS_OF)
        assert base["breakdown"]["goal_earmarks"] == 250.0

        # Hypothetically bump the earmarked progress to $400.
        out = svc.safe_to_spend(
            _as_user_in_db(user), AS_OF,
            overlay=ScenarioOverlay(
                goal_mutations=(
                    GoalMutation(goal_id=goal.id, progress_cents=40_000),
                ),
            ),
        )
        assert out["breakdown"]["goal_earmarks"] == 400.0
        # Higher earmark → lower available than the baseline.
        assert out["available"] < base["available"]
        # The stored goal progress is unchanged.
        assert goal.progress == 25_000

    def test_balance_override_replaces_summed_balance(self, db_session, s2s_user):
        user, _ = s2s_user  # real balance $1,000
        user.s2s_horizon = "month"
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(
            _as_user_in_db(user), AS_OF,
            overlay=ScenarioOverlay(balance_override_cents=500_00),  # $500...
        )
        assert out["breakdown"]["current_balance"] == 500.0
        assert out["available"] == 500.0

    def test_added_expense_overlay_reduces_available(self, db_session, s2s_user):
        """An overlay that injects a one-off expense lowers spendable, proving the
        overlay threads all the way into project_cashflows."""
        from server.src.services.scenario_overlay import DiscreteFlow

        user, _ = s2s_user
        user.s2s_horizon = "month"  # horizon 3/31
        db_session.flush()
        svc = SpendService(db_session)
        base = svc.safe_to_spend(_as_user_in_db(user), AS_OF)
        out = svc.safe_to_spend(
            _as_user_in_db(user), AS_OF,
            overlay=ScenarioOverlay(
                discrete_flows=(
                    DiscreteFlow(date="2026-03-20", amount_cents=15_000,
                                 kind="expense"),  # $150 surprise bill
                ),
            ),
        )
        assert out["breakdown"]["upcoming_bills"] == base["breakdown"]["upcoming_bills"] + 150.0
        assert out["available"] == base["available"] - 150.0
