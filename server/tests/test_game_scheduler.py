"""Step 09 — the production game scheduler (APScheduler).

The job FUNCTIONS are tested directly (idempotent month-close, kill-switch
respect, outcomes population). APScheduler itself is NEVER started in the suite
(``scheduler_enabled=False``) so the tests are deterministic.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from server.src.db.models import (
    Account as AccountORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    HeatContract,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import experiments, folds as folds_mod
from server.src.services.game.metrics import outcomes_summary
from server.src import scheduler


@pytest.fixture
def user_acct(db_session):
    folds_mod.register_builtin_folds()
    user = UserORM(username="sched", full_name="Sched U", email="sched@x.com",
                   hashed_password="x", savings_percent=0)
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=500_00,
                      user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


def _sealed_count(db, month: str) -> int:
    return db.execute(text(
        "SELECT COUNT(*) FROM game_events WHERE type='MonthSealed' "
        "AND idempotency_key LIKE :k"
    ), {"k": f"seal:%:{month}"}).scalar_one()


def test_run_due_game_jobs_closes_month_idempotently(db_session, user_acct):
    user, acct = user_acct
    # A discretionary expense in the rollup month so weekly rollups produce a
    # MetricRollup → /game/outcomes/ becomes populated.
    db_session.add(ExpenseORM(title="Fun", amount=40_00, date="2026-07-01",
                              category="Fun", account_id=acct.id))
    db_session.flush()

    now = date(2026, 7, 1)  # month boundary → seals June (2026-06)
    sealed_month = "2026-06"

    # First run: seals the prior month exactly once.
    scheduler.run_due_game_jobs(db_session, now)
    db_session.flush()
    assert _sealed_count(db_session, sealed_month) == 1

    # /game/outcomes/ is now populated (weekly rollup wrote a MetricRollup row).
    summary = outcomes_summary(db_session)
    assert summary["comparison"], "expected outcomes to be populated after rollups"

    # Re-running is a NO-OP: no second seal (idempotent on seal:{user}:{month}).
    scheduler.run_due_game_jobs(db_session, now)
    db_session.flush()
    assert _sealed_count(db_session, sealed_month) == 1


def test_run_due_game_jobs_no_month_close_mid_month(db_session, user_acct):
    """A non-boundary fire runs rollups/fade but does NOT seal a month."""
    user, acct = user_acct
    scheduler.run_due_game_jobs(db_session, date(2026, 7, 15))
    db_session.flush()
    # No MonthSealed emitted mid-month.
    sealed = db_session.execute(text(
        "SELECT COUNT(*) FROM game_events WHERE type='MonthSealed'"
    )).scalar_one()
    assert sealed == 0


def test_scheduler_disabled_in_tests(monkeypatch):
    """With scheduler_enabled=False, start_scheduler does NOT start APScheduler
    (no background fires during the suite)."""
    from server.src.settings import settings

    monkeypatch.setattr(settings, "scheduler_enabled", False)
    sched = scheduler.start_scheduler()
    assert sched is None


def test_scheduler_builds_declarative_cron_jobs():
    """The built scheduler registers exactly its declarative cron jobs (monthly
    month-close/fade + weekly rollups + the v6 daily plan-drift check + the
    messy-data daily Detangler + the Pillar-3 daily quarterly-tax reminder + the
    F3 nightly Auditor). Built, not started, so no event loop / background fire is
    needed. Like ``detangle``, ``auditor`` and ``tax_quarterly_reminder`` are
    ALWAYS registered and self-gate on their feature flag at the tick, so the job
    set is independent of the flag."""
    sched = scheduler.build_scheduler()
    assert {j.id for j in sched.get_jobs()} == {
        "game_monthly",
        "game_weekly",
        "plan_drift",
        "detangle",
        "tax_quarterly_reminder",
        "auditor",
    }


def test_scheduler_starts_and_stops_when_enabled(monkeypatch):
    """When enabled and inside an event loop, start_scheduler returns a running
    scheduler; we shut it down so nothing fires during the rest of the suite."""
    import asyncio

    from server.src.settings import settings

    monkeypatch.setattr(settings, "scheduler_enabled", True)

    async def _drive():
        sched = scheduler.start_scheduler()
        try:
            assert sched is not None
            assert sched.running
        finally:
            scheduler.shutdown_scheduler(sched)

    asyncio.run(_drive())


def test_scheduler_respects_killed_features(db_session, user_acct):
    """With killed_features including 'heat', the heat resolution job does not
    run: month-close voids active heat contracts (soft landing) instead of
    resolving them met/unmet, and produces no sweep proposals."""
    user, acct = user_acct
    # An active heat contract for June.
    contract = HeatContract(
        user_id=user.id, category="Dining", kind="cap_vs_baseline",
        target_param=75, heat_value=1, month="2026-06", status="active",
        arm="sweep",
    )
    db_session.add(contract)
    db_session.add(CategorySettingsORM(name="Dining", essential=0, user_confirmed=1))
    db_session.flush()

    experiments.kill("heat")
    try:
        result = scheduler.run_due_game_jobs(db_session, date(2026, 7, 1))
        db_session.flush()
    finally:
        experiments.revive("heat")

    db_session.refresh(contract)
    # Heat killed → contract voided (soft landing), never resolved met/unmet.
    assert contract.status == "void"
    mc = result.get("month_close", {})
    sealed = mc.get("sealed", {}).get(user.id, {})
    assert sealed.get("sweep_proposals", []) == []


def test_fade_job_skipped_when_bestiary_killed(db_session, user_acct):
    user, acct = user_acct
    db_session.add(CategorySettingsORM(name="Dining", essential=0, user_confirmed=1))
    db_session.flush()
    experiments.kill("bestiary")
    try:
        out = scheduler.job_fade_and_graduation(db_session, date(2026, 7, 8))
    finally:
        experiments.revive("bestiary")
    assert out == {"skipped": "bestiary_killed"}


# ── v6 doc 06: plan-of-record drift is the first scheduler notification job ───


def test_job_check_plan_drift_notifies_and_dedups(db_session, user_acct):
    """The drift job re-checks active plans across users and is idempotent.

    Drives drift through a goal-slip snapshot (deterministic, seed-independent),
    then re-runs to confirm the ``ref`` dedup holds — a scheduler double-fire
    must not double-notify (R8)."""
    import json
    from datetime import date as _date

    from server.src.db.models import (
        Goal as GoalORM,
        Notification as NotificationORM,
        PlanOfRecord as PlanOfRecordORM,
    )
    from server.src.services.scenario_overlay import EMPTY
    from server.src.services.scenario_service import ScenarioService

    user, _acct = user_acct
    as_of = _date(2026, 3, 10)
    goal = GoalORM(name="Trip", amount=120_000, progress=20_000,
                   date="2026-12-01", user_id=user.id, completed=0)
    db_session.add(goal)
    db_session.flush()

    # Live reach date, then a snapshot that reaches 3 months earlier → live has
    # slipped well past the 14-day threshold.
    import random
    live = ScenarioService(db_session).evaluate(
        user.id, EMPTY, as_of=as_of, rng=random.Random(0)
    )["baseline"]["result"]
    live_reach = live["goal_reach"].get(goal.id, {}).get("reaches_on") or "2026-12-01"
    y, m, _d = map(int, live_reach.split("-"))
    m = m - 3 if m > 3 else m + 9
    snap_result = dict(live)
    snap_result["goal_reach"] = {str(goal.id): {"reaches_on": _date(y, m, 1).isoformat()}}
    db_session.add(PlanOfRecordORM(
        user_id=user.id, scenario_id=None, rule_ids_json=json.dumps([]),
        baseline_snapshot_json=json.dumps({
            "baseline": {"name": "Baseline", "result": snap_result},
            "scenario": {"name": "Plan", "scenario_id": None,
                         "result": snap_result, "delta": {}},
        }),
        status="active",
    ))
    db_session.flush()

    first = scheduler.job_check_plan_drift(db_session, as_of)
    second = scheduler.job_check_plan_drift(db_session, as_of)
    assert first == 1
    assert second == 0  # ref dedup — no second notification on re-fire

    count = db_session.query(NotificationORM).filter(
        NotificationORM.type == "plan_drift"
    ).count()
    assert count == 1
