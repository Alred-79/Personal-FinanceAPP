"""Plan-of-record drift tracking (v6 doc 06).

A committed :class:`PlanOfRecord` locks a snapshot at commit time. ``check_drift``
re-evaluates current reality (the EMPTY-overlay live column) against that snapshot
and fires ONE deduped ``plan_drift`` notification when a tracked metric has
slipped past threshold. Re-running is idempotent (``ref`` dedup); within-threshold
drift is silent; ``last_checked_at`` is stamped on every plan examined.

The integration snapshots start from current reality and then current cash is
lowered so overdraft risk rises deterministically. Goal-slip classification is
tested as a pure contract; an unknown goal pace must never manufacture drift.
"""

import json
import random
from datetime import date

import pytest

from server.src.db.models import (
    Account,
    Goal,
    Income,
    Notification as NotificationORM,
    PlanOfRecord as PlanOfRecordORM,
    User,
)
from server.src.services.scenario_overlay import EMPTY
from server.src.services.scenario_service import ScenarioService

AS_OF = date(2026, 3, 10)


@pytest.fixture
def funded_user(db_session):
    user = User(
        username="drift_user",
        full_name="Drift User",
        email="drift@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        Account(name="Checking", type="checking", balance=300_000, user_id=user.id)
    )
    db_session.flush()
    db_session.add(
        Income(
            title="Paycheck",
            amount=200_000,
            date="2026-03-01",
            category="Work",
            recurrence="bi-weekly",
            account_id=db_session.query(Account).first().id,
        )
    )
    db_session.flush()
    return user


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


def _commit_plan(db_session, user_id, snapshot_scenario_result, status="active"):
    """Insert a PlanOfRecord whose snapshot's scenario.result is as supplied."""
    snapshot = {
        "baseline": {"name": "Baseline", "result": snapshot_scenario_result},
        "scenario": {
            "name": "Plan",
            "scenario_id": None,
            "result": snapshot_scenario_result,
            "delta": {},
        },
    }
    plan = PlanOfRecordORM(
        user_id=user_id,
        scenario_id=None,
        rule_ids_json=json.dumps([]),
        baseline_snapshot_json=json.dumps(snapshot),
        status=status,
    )
    db_session.add(plan)
    db_session.flush()
    return plan


def _live_result(db_session, user_id):
    """Current reality's metric set — exactly what ``check_drift`` compares to."""
    return ScenarioService(db_session).evaluate(
        user_id, EMPTY, as_of=AS_OF, rng=random.Random(0)
    )["baseline"]["result"]


# ── Drift-reason classification (pure, deterministic) ────────────────────────


def test_drift_reasons_overdraft_rise_past_threshold():
    """Overdraft risen by > 0.10 → a reason; equal/under → silent; a drop → silent."""
    reasons = ScenarioService._drift_reasons(
        {"overdraft_probability": 0.05, "goal_reach": {}},
        {"overdraft_probability": 0.25, "goal_reach": {}},  # +0.20 > 0.10
    )
    assert len(reasons) == 1 and "overdraft" in reasons[0]

    # Within threshold (+0.08) → nothing.
    assert ScenarioService._drift_reasons(
        {"overdraft_probability": 0.05, "goal_reach": {}},
        {"overdraft_probability": 0.13, "goal_reach": {}},
    ) == []

    # Reality came out BETTER (lower risk) → never a nag.
    assert ScenarioService._drift_reasons(
        {"overdraft_probability": 0.40, "goal_reach": {}},
        {"overdraft_probability": 0.05, "goal_reach": {}},
    ) == []


def test_drift_reasons_goal_slip_past_threshold():
    """A goal reaching > 14 days later → a reason; sooner/within → silent."""
    planned = {"overdraft_probability": 0.0, "goal_reach": {"7": {"reaches_on": "2026-06-01"}}}
    later = {"overdraft_probability": 0.0, "goal_reach": {7: {"reaches_on": "2026-07-01"}}}
    reasons = ScenarioService._drift_reasons(planned, later)  # 30 days later
    assert len(reasons) == 1 and "goal 7" in reasons[0]

    within = {"overdraft_probability": 0.0, "goal_reach": {7: {"reaches_on": "2026-06-10"}}}
    assert ScenarioService._drift_reasons(planned, within) == []  # 9 days

    sooner = {"overdraft_probability": 0.0, "goal_reach": {7: {"reaches_on": "2026-05-01"}}}
    assert ScenarioService._drift_reasons(planned, sooner) == []  # ahead of plan

    unknown = {"overdraft_probability": 0.0, "goal_reach": {7: {"reaches_on": None}}}
    assert ScenarioService._drift_reasons(planned, unknown) == []


# ── Goal-slip drift through the full check_drift path ────────────────────────


def test_cash_risk_drift_fires_one_notification(db_session, funded_user):
    user = funded_user
    plan = _commit_cash_risk_plan(db_session, user.id)

    drifted = ScenarioService(db_session).check_drift(user.id, as_of=AS_OF)
    assert drifted == [plan.id]
    notifs = (
        db_session.query(NotificationORM)
        .filter(NotificationORM.type == "plan_drift")
        .all()
    )
    assert len(notifs) == 1
    # ref embeds plan id + period so a new month can re-fire, same month cannot.
    assert notifs[0].ref == f"plan_drift:{plan.id}:2026-03"
    # last_checked_at is stamped.
    db_session.refresh(plan)
    assert plan.last_checked_at is not None


def _commit_cash_risk_plan(db_session, user_id):
    """Lock today's plan, then create a deterministic cash-risk increase."""
    live = _live_result(db_session, user_id)
    plan = _commit_plan(db_session, user_id, dict(live))
    account = db_session.query(Account).filter(Account.user_id == user_id).one()
    account.balance = -100_000
    db_session.flush()
    return plan


# ── Idempotency: a re-run does not duplicate ─────────────────────────────────


def test_drift_is_deduped_on_rerun(db_session, funded_user):
    user = funded_user
    _commit_cash_risk_plan(db_session, user.id)

    svc = ScenarioService(db_session)
    first = svc.check_drift(user.id, as_of=AS_OF)
    second = svc.check_drift(user.id, as_of=AS_OF)
    assert len(first) == 1
    assert second == []  # same period → no new notification

    notifs = (
        db_session.query(NotificationORM)
        .filter(NotificationORM.type == "plan_drift")
        .count()
    )
    assert notifs == 1


# ── Within-threshold drift fires nothing ─────────────────────────────────────


def test_within_threshold_is_silent(db_session, funded_user):
    user = funded_user
    _goal(db_session, user.id)
    # Snapshot == current reality, so there is zero drift to report.
    live = _live_result(db_session, user.id)
    # goal_reach keys come back as ints from evaluate; store as-is — the snapshot
    # round-trips them to strings, which check_drift tolerates.
    plan = _commit_plan(db_session, user.id, live)

    drifted = ScenarioService(db_session).check_drift(user.id, as_of=AS_OF)
    assert drifted == []
    assert (
        db_session.query(NotificationORM)
        .filter(NotificationORM.type == "plan_drift")
        .count()
        == 0
    )
    # last_checked_at is still stamped even with no drift.
    db_session.refresh(plan)
    assert plan.last_checked_at is not None


# ── Retired plans are not checked ────────────────────────────────────────────


def test_inactive_plan_is_skipped(db_session, funded_user):
    user = funded_user
    # A snapshot that WOULD drift, but on a retired plan, so it is never examined.
    live = _live_result(db_session, user.id)
    plan = _commit_plan(db_session, user.id, dict(live), status="retired")
    account = db_session.query(Account).filter(Account.user_id == user.id).one()
    account.balance = -100_000
    db_session.flush()

    drifted = ScenarioService(db_session).check_drift(user.id, as_of=AS_OF)
    assert drifted == []
    # An inactive plan is never examined, so its last_checked_at stays unset.
    db_session.refresh(plan)
    assert plan.last_checked_at is None
