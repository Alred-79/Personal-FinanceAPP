"""Scenario evaluate + compare (v6 doc 04) — the diff engine.

``evaluate`` turns a saved overlay into a Baseline-vs-Scenario diff over a
horizon; ``compare`` lines up N scenarios against one shared baseline. Both reuse
the overlay-aware forecast / safe-to-spend engines (docs 01-02) and the promoted
goal-math helpers, share ONE seeded ``rng`` across every column (apples-to-apples,
R5), and use ``ScenarioOverlay.EMPTY`` for the baseline so baseline == live (R1).

All diffs are computed in cents server-side; the values here are dollars at the
boundary.
"""

import random
from datetime import date

import pytest

from server.src.db.models import Account, Goal, Income, User
from server.src.services.scenario_overlay import (
    DiscreteFlow,
    GoalMutation,
    RecurringAdd,
    ScenarioOverlay,
)
from server.src.services.scenario_service import ScenarioService

AS_OF = date(2026, 3, 10)
METRIC_KEYS = {
    "overdraft_probability",
    "lowest_balance",
    "ending_balance",
    "safe_to_spend",
    "runway_days",
    "goal_reach",
}


@pytest.fixture
def funded_user(db_session):
    user = User(
        username="eval_user",
        full_name="Eval User",
        email="eval@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    acct = Account(
        name="Checking", type="checking", balance=300_000, user_id=user.id
    )  # $3,000
    db_session.add(acct)
    db_session.flush()
    # A bi-weekly paycheck so the projection has income to reshape.
    db_session.add(
        Income(
            title="Paycheck",
            amount=200_000,
            date="2026-03-01",
            category="Work",
            recurrence="bi-weekly",
            account_id=acct.id,
        )
    )
    db_session.flush()
    return user, acct


def _goal(db_session, user_id, amount=120_000, progress=20_000, date_str="2026-12-01"):
    g = Goal(
        name="Emergency",
        amount=amount,
        progress=progress,
        date=date_str,
        user_id=user_id,
        completed=0,
    )
    db_session.add(g)
    db_session.flush()
    return g


class TestEvaluate:
    def test_baseline_equals_live(self, db_session, funded_user):
        """The baseline column uses EMPTY, so it must equal a direct EMPTY run."""
        user, _ = funded_user
        svc = ScenarioService(db_session)
        out = svc.evaluate(
            user.id, _empty(), as_of=AS_OF, horizon_days=90, rng=random.Random(0)
        )
        # An EMPTY overlay scenario produces a zero delta against the baseline.
        assert out["baseline"]["result"]["ending_balance"] == \
            out["scenario"]["result"]["ending_balance"]
        assert out["scenario"]["delta"]["ending_balance"] == 0.0
        assert out["scenario"]["delta"]["lowest_balance"] == 0.0
        assert out["scenario"]["delta"]["overdraft_probability"] == 0.0

    def test_result_metric_shape(self, db_session, funded_user):
        user, _ = funded_user
        _goal(db_session, user.id)
        svc = ScenarioService(db_session)
        out = svc.evaluate(
            user.id, _empty(), as_of=AS_OF, horizon_days=90, rng=random.Random(0)
        )
        for col in (out["baseline"], out["scenario"]):
            assert METRIC_KEYS <= set(col["result"].keys())
            assert col["result"]["safe_to_spend_horizon_end"] == "2026-06-08"
            assert col["result"]["safe_to_spend_horizon_source"] == "decision_horizon"
        # goal_reach is keyed per goal.
        gr = out["baseline"]["result"]["goal_reach"]
        assert isinstance(gr, dict)

    def test_added_income_raises_ending_balance(self, db_session, funded_user):
        """An injected income stream lifts the scenario's ending balance."""
        user, _ = funded_user
        svc = ScenarioService(db_session)
        overlay = ScenarioOverlay(
            added_recurring=(
                RecurringAdd(
                    title="Side gig",
                    amount_cents=50_000,
                    recurrence="monthly",
                    kind="income",
                    anchor_date="2026-03-15",
                ),
            )
        )
        out = svc.evaluate(
            user.id, overlay, as_of=AS_OF, horizon_days=90, rng=random.Random(0)
        )
        assert out["scenario"]["delta"]["ending_balance"] > 0.0

    def test_balance_override_shifts_lowest(self, db_session, funded_user):
        user, _ = funded_user
        svc = ScenarioService(db_session)
        overlay = ScenarioOverlay(balance_override_cents=10_000)  # $100 only
        out = svc.evaluate(
            user.id, overlay, as_of=AS_OF, horizon_days=90, rng=random.Random(0)
        )
        # Starting far lower drops both lowest and ending by the same shift.
        assert out["scenario"]["delta"]["lowest_balance"] < 0.0
        assert out["scenario"]["delta"]["ending_balance"] < 0.0

    def test_goal_mutation_moves_reach_date(self, db_session, funded_user):
        """Injecting progress into a goal makes it reach sooner (delta_days < 0)."""
        user, _ = funded_user
        g = _goal(db_session, user.id, amount=120_000, progress=20_000)
        svc = ScenarioService(db_session)
        overlay = ScenarioOverlay(
            goal_mutations=(GoalMutation(goal_id=g.id, progress_cents=100_000),)
        )
        out = svc.evaluate(
            user.id, overlay, as_of=AS_OF, horizon_days=90, rng=random.Random(0)
        )
        gr = out["scenario"]["delta"]["goal_reach"]
        assert g.id in gr
        assert gr[g.id]["delta_days"] <= 0

    def test_determinism_same_seed(self, db_session, funded_user):
        """Two runs with the same seed give the identical overdraft probability."""
        user, _ = funded_user
        svc = ScenarioService(db_session)
        overlay = ScenarioOverlay(
            discrete_flows=(
                DiscreteFlow(date="2026-04-01", amount_cents=250_000, kind="expense"),
            )
        )
        a = svc.evaluate(user.id, overlay, as_of=AS_OF, rng=random.Random(0))
        b = svc.evaluate(user.id, overlay, as_of=AS_OF, rng=random.Random(0))
        assert a["scenario"]["result"]["overdraft_probability"] == \
            b["scenario"]["result"]["overdraft_probability"]
        assert a["baseline"]["result"]["overdraft_probability"] == \
            b["baseline"]["result"]["overdraft_probability"]


class TestCompare:
    def test_two_scenarios_share_one_baseline(self, db_session, funded_user):
        user, _ = funded_user
        svc = ScenarioService(db_session)
        s1 = svc.create(
            user.id, "Tight",
            _overlay_in(balance_override=100.0),
        )
        s2 = svc.create(
            user.id, "Flush",
            _overlay_in(balance_override=9000.0),
        )
        out = svc.compare(
            user.id, [s1.id, s2.id], as_of=AS_OF, horizon_days=90, rng=random.Random(0)
        )
        cols = out["columns"]
        # baseline + 2 scenario columns.
        assert len(cols) == 3
        assert cols[0]["name"] == "Baseline"
        assert "scenario_id" not in cols[0] or cols[0].get("scenario_id") is None
        assert cols[1]["scenario_id"] == s1.id
        assert cols[2]["scenario_id"] == s2.id
        # Baseline has no delta; scenario columns do.
        assert cols[0].get("delta") in (None, {})
        assert cols[1]["delta"]["ending_balance"] < cols[2]["delta"]["ending_balance"]

    def test_compare_is_deterministic(self, db_session, funded_user):
        user, _ = funded_user
        svc = ScenarioService(db_session)
        s1 = svc.create(user.id, "A", _overlay_in())
        a = svc.compare(user.id, [s1.id], as_of=AS_OF, rng=random.Random(0))
        b = svc.compare(user.id, [s1.id], as_of=AS_OF, rng=random.Random(0))
        assert a["columns"][0]["result"]["overdraft_probability"] == \
            b["columns"][0]["result"]["overdraft_probability"]

    def test_unknown_scenario_id_is_skipped_or_errors(self, db_session, funded_user):
        """A scenario id the user does not own must not leak another's data."""
        user, _ = funded_user
        svc = ScenarioService(db_session)
        with pytest.raises(KeyError):
            svc.compare(user.id, [999_999], as_of=AS_OF, rng=random.Random(0))


# ── helpers ──────────────────────────────────────────────────────────────────


def _empty():
    return ScenarioOverlay()


def _overlay_in(balance_override=None):
    """A dollar ScenarioOverlayIn for create()."""
    from server.src.models import ScenarioOverlayIn

    return ScenarioOverlayIn(balance_override=balance_override)
