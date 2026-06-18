"""W7 — Behavioral features (Tier-1, evidence-graded) tests.

Covers the four forecast-gated nudges (F1/F2/F4/F6) per the spec:
  * F2 escalation SKIPS the bump when the forecast says it would push the user
    negative (the HARD forecast veto) and applies it when the forecast is healthy;
  * F1 reminders respect the per-week cadence cap and the user mute (suppress winners);
  * F4 earmarks are always reversible (pull-back allowed, no penalty) and warn (never
    block) on a near-term bill;
  * F6 landmark re-entry targets LAPSED users only, never engaged ones, and never
    touches the streak machine;
  * every feature is flag-gated (no-op when off);
  * a POSTGRES test asserting the escalation job binds per-user RLS tenant context and
    ACTUALLY reads the user's rules under RLS (not zero) — the classic RLS trap.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.src import scheduler
from server.src.db.models import (
    Account as AccountORM,
    Earmark as EarmarkORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Notification as NotificationORM,
    Rule as RuleORM,
    User as UserORM,
)
from server.src.db.rls import enable_rls, set_tenant
from server.src.services import behavioral
from server.src.services.behavioral import (
    EarmarkError,
    EarmarkService,
    is_lapsed,
    is_muted,
    run_escalation,
    run_goal_reminders,
    run_landmark_reentry,
    set_reminder_mute,
)
from server.src.settings import settings

_NOW = date(2026, 6, 15)
_PG = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


# ── helpers ──────────────────────────────────────────────────────────────────


def _user(db, name="beh", balance=500_00):
    u = UserORM(
        username=name, full_name="Beh U", email=f"{name}@x.com", hashed_password="x"
    )
    db.add(u)
    db.flush()
    acct = AccountORM(name="Checking", type="checking", balance=balance, user_id=u.id)
    db.add(acct)
    db.flush()
    return u, acct


def _goal(db, user_id, *, name="Vacation", amount=1000_00, progress=400_00, completed=0):
    g = GoalORM(
        name=name,
        amount=amount,
        date="2026-12-31",
        user_id=user_id,
        progress=progress,
        completed=completed,
    )
    db.add(g)
    db.flush()
    return g


def _allocate_rule(db, user_id, goal_id, params):
    r = RuleORM(
        user_id=user_id,
        name="Save more",
        enabled=1,
        conditions="[]",
        action_type="allocate",
        action_params=json.dumps(params),
        target_kind="goal",
        target_id=goal_id,
    )
    db.add(r)
    db.flush()
    return r


def _enable(name):
    """Context-free flag flip helper used inline with try/finally."""
    saved = getattr(settings, name)
    setattr(settings, name, True)
    return saved


# ── F2: escalation forecast veto (the hard requirement) ───────────────────────


def test_escalation_skips_when_forecast_would_go_negative(db_session):
    """THE headline veto: with a low balance + a recurring bill that troughs the
    forecast at/below the bump, the escalation must be VETOED (action_params unchanged)."""
    u, acct = _user(db_session, balance=50_00)  # only $50 on hand
    # A $100/month recurring expense → the burn-aware forecast troughs negative soon.
    db_session.add(
        ExpenseORM(
            title="Rent", amount=100_00, date="2026-06-20", category="Housing",
            recurrence="monthly", account_id=acct.id,
        )
    )
    db_session.flush()
    g = _goal(db_session, u.id)
    rule = _allocate_rule(
        db_session, u.id, g.id,
        {"amount": 50, "escalation": {"step_amount": 25, "max_amount": 200}},
    )

    saved = _enable("behavioral_escalation_enabled")
    try:
        summary = run_escalation(db_session, u.id, now=_NOW)
    finally:
        settings.behavioral_escalation_enabled = saved

    assert summary["vetoed"] == 1
    assert summary["bumped"] == 0
    # action_params must be UNTOUCHED — no bump, no period stamp.
    params = json.loads(rule.action_params)
    assert params["amount"] == 50
    assert "last_escalated_period" not in params["escalation"]


def test_escalation_applies_when_forecast_is_healthy(db_session):
    """The complement: a healthy (high balance, no looming bill) forecast lets the bump
    through, and the rule's amount + period stamp are updated (idempotent next run)."""
    u, acct = _user(db_session, balance=10_000_00)  # plenty of headroom
    g = _goal(db_session, u.id)
    rule = _allocate_rule(
        db_session, u.id, g.id,
        {"amount": 50, "escalation": {"step_amount": 25, "max_amount": 200}},
    )

    saved = _enable("behavioral_escalation_enabled")
    try:
        summary = run_escalation(db_session, u.id, now=_NOW)
        params = json.loads(rule.action_params)
        assert summary["bumped"] == 1
        assert params["amount"] == 75  # 50 + 25
        assert params["escalation"]["last_escalated_period"] == "2026-06"

        # Idempotent within the same month: a second run does NOT bump again.
        summary2 = run_escalation(db_session, u.id, now=_NOW)
        assert summary2["bumped"] == 0
        assert json.loads(rule.action_params)["amount"] == 75
    finally:
        settings.behavioral_escalation_enabled = saved


def test_escalation_respects_ceiling(db_session):
    """At ``max_amount`` there is nothing to bump — the rule is skipped, not bumped."""
    u, acct = _user(db_session, balance=10_000_00)
    g = _goal(db_session, u.id)
    rule = _allocate_rule(
        db_session, u.id, g.id,
        {"amount": 200, "escalation": {"step_amount": 25, "max_amount": 200}},
    )
    saved = _enable("behavioral_escalation_enabled")
    try:
        summary = run_escalation(db_session, u.id, now=_NOW)
    finally:
        settings.behavioral_escalation_enabled = saved
    assert summary["bumped"] == 0
    assert summary["skipped"] == 1
    assert json.loads(rule.action_params)["amount"] == 200


def test_escalation_flag_off_is_noop(db_session):
    u, acct = _user(db_session, balance=10_000_00)
    g = _goal(db_session, u.id)
    rule = _allocate_rule(
        db_session, u.id, g.id,
        {"amount": 50, "escalation": {"step_amount": 25, "max_amount": 200}},
    )
    # flag is False by default
    summary = run_escalation(db_session, u.id, now=_NOW)
    assert summary == {"skipped": 0, "bumped": 0, "vetoed": 0}
    assert json.loads(rule.action_params)["amount"] == 50


def test_escalation_ignores_rules_without_escalation_block(db_session):
    u, acct = _user(db_session, balance=10_000_00)
    g = _goal(db_session, u.id)
    rule = _allocate_rule(db_session, u.id, g.id, {"amount": 50})  # no escalation opt-in
    saved = _enable("behavioral_escalation_enabled")
    try:
        summary = run_escalation(db_session, u.id, now=_NOW)
    finally:
        settings.behavioral_escalation_enabled = saved
    assert summary["bumped"] == 0
    assert json.loads(rule.action_params) == {"amount": 50}


# ── F1: goal-named reminders — cadence cap + mute ─────────────────────────────


def test_goal_reminder_names_goal_and_progress(db_session):
    u, _ = _user(db_session)
    g = _goal(db_session, u.id, name="New Laptop", amount=2000_00, progress=500_00)
    saved = _enable("behavioral_goal_reminders_enabled")
    try:
        summary = run_goal_reminders(db_session, u.id, now=_NOW)
    finally:
        settings.behavioral_goal_reminders_enabled = saved
    assert summary["created"] == 1
    notif = db_session.execute(
        text("SELECT title, message FROM notifications WHERE type='goal_reminder'")
    ).first()
    assert "New Laptop" in notif[0]
    assert "500.00" in notif[1] and "2,000.00" in notif[1]


def test_goal_reminder_respects_cadence_cap(db_session):
    """At most ``behavioral_reminder_max_per_week`` (=1) per goal per week — a second
    run in the same week adds NO new reminder."""
    u, _ = _user(db_session)
    _goal(db_session, u.id, progress=400_00)
    saved = _enable("behavioral_goal_reminders_enabled")
    try:
        first = run_goal_reminders(db_session, u.id, now=_NOW)
        second = run_goal_reminders(db_session, u.id, now=_NOW)
    finally:
        settings.behavioral_goal_reminders_enabled = saved
    assert first["created"] == 1
    assert second["created"] == 0
    count = db_session.execute(
        text("SELECT count(*) FROM notifications WHERE type='goal_reminder'")
    ).scalar()
    assert count == 1


def test_goal_reminder_suppressed_when_muted(db_session):
    """Mute is the reminder-fatigue escape hatch: a muted user gets NO reminders, and
    un-muting is fully reversible (reminders resume)."""
    u, _ = _user(db_session)
    _goal(db_session, u.id, progress=400_00)
    set_reminder_mute(db_session, u.id, True)
    assert is_muted(db_session, u.id) is True
    saved = _enable("behavioral_goal_reminders_enabled")
    try:
        muted_run = run_goal_reminders(db_session, u.id, now=_NOW)
        assert muted_run["created"] == 0
        # Un-mute → reminders resume (reversible).
        set_reminder_mute(db_session, u.id, False)
        assert is_muted(db_session, u.id) is False
        resumed = run_goal_reminders(db_session, u.id, now=_NOW)
    finally:
        settings.behavioral_goal_reminders_enabled = saved
    assert resumed["created"] == 1


def test_goal_reminder_skips_unfunded_and_completed(db_session):
    u, _ = _user(db_session)
    _goal(db_session, u.id, name="Empty", progress=0)  # unfunded → skip
    _goal(db_session, u.id, name="Done", amount=100_00, progress=100_00, completed=1)
    saved = _enable("behavioral_goal_reminders_enabled")
    try:
        summary = run_goal_reminders(db_session, u.id, now=_NOW)
    finally:
        settings.behavioral_goal_reminders_enabled = saved
    assert summary["created"] == 0


def test_goal_reminder_flag_off_is_noop(db_session):
    u, _ = _user(db_session)
    _goal(db_session, u.id, progress=400_00)
    summary = run_goal_reminders(db_session, u.id, now=_NOW)
    assert summary["created"] == 0


# ── F4: soft earmarks — always reversible, warn-not-block ─────────────────────


def test_earmark_set_list_and_pull_back(db_session):
    """An earmark is a soft, named sub-bucket; pulling it back (release) is always
    allowed, instant, and leaves no residue."""
    u, _ = _user(db_session)
    g = _goal(db_session, u.id, progress=400_00)
    svc = EarmarkService(db_session)

    out = svc.set_earmark(u.id, g.id, "Deposit", 150_00, now=_NOW)
    assert out["amount_cents"] == 150_00
    assert svc.list(u.id, g.id)[0]["name"] == "Deposit"

    # Resize DOWN is always permitted (pull-back / over-restriction guard).
    out2 = svc.set_earmark(u.id, g.id, "Deposit", 50_00, now=_NOW)
    assert out2["amount_cents"] == 50_00

    # Release entirely — reversible, no penalty, row gone.
    assert svc.release(u.id, g.id, "Deposit") is True
    assert svc.list(u.id, g.id) == []
    # Goal progress is never frozen / never mutated by the label.
    assert db_session.get(GoalORM, g.id).progress == 400_00


def test_earmark_cannot_exceed_progress_but_decrease_always_ok(db_session):
    """Raising an earmark above the goal's saved progress is rejected (can't earmark
    money you haven't saved); lowering is ALWAYS allowed."""
    u, _ = _user(db_session)
    g = _goal(db_session, u.id, progress=100_00)
    svc = EarmarkService(db_session)
    with pytest.raises(EarmarkError):
        svc.set_earmark(u.id, g.id, "Too big", 200_00, now=_NOW)
    svc.set_earmark(u.id, g.id, "Ok", 100_00, now=_NOW)
    # A decrease is always allowed even though nothing else changed.
    out = svc.set_earmark(u.id, g.id, "Ok", 10_00, now=_NOW)
    assert out["amount_cents"] == 10_00


def test_earmark_warns_but_does_not_block_on_near_term_bill(db_session):
    """When the forecast sees a near-term shortfall, set_earmark WARNS — it never
    raises or blocks the earmark (the locked-savings backfire guard)."""
    u, acct = _user(db_session, balance=50_00)
    db_session.add(
        ExpenseORM(
            title="Rent", amount=100_00, date="2026-06-20", category="Housing",
            recurrence="monthly", account_id=acct.id,
        )
    )
    db_session.flush()
    g = _goal(db_session, u.id, progress=40_00)
    svc = EarmarkService(db_session)
    out = svc.set_earmark(u.id, g.id, "Buffer", 40_00, now=_NOW)
    # The earmark still succeeded (not blocked) but carries an advisory warning.
    assert out["amount_cents"] == 40_00
    assert out["warning"] is not None
    assert "release it any time" in out["warning"]


def test_earmark_release_missing_is_false(db_session):
    u, _ = _user(db_session)
    g = _goal(db_session, u.id, progress=400_00)
    assert EarmarkService(db_session).release(u.id, g.id, "nope") is False


# ── F6: landmark re-entry — lapsed only, never engaged ────────────────────────


def test_landmark_targets_lapsed_user(db_session):
    """A user with no recent activity is LAPSED → gets one gentle re-entry notice."""
    u, acct = _user(db_session)
    # Last activity 60 days ago → lapsed (default threshold 30 days).
    db_session.add(
        ExpenseORM(
            title="Old", amount=10_00, date=(_NOW - timedelta(days=60)).isoformat(),
            category="Food", account_id=acct.id,
        )
    )
    db_session.flush()
    assert is_lapsed(db_session, u.id, _NOW) is True
    saved = _enable("behavioral_landmark_enabled")
    try:
        summary = run_landmark_reentry(db_session, u.id, now=date(2026, 6, 1))
    finally:
        settings.behavioral_landmark_enabled = saved
    assert summary["created"] == 1


def test_landmark_skips_engaged_user(db_session):
    """An engaged user (recent activity) is NEVER nudged — the what-the-hell licensing
    guard. No notification is created."""
    u, acct = _user(db_session)
    db_session.add(
        ExpenseORM(
            title="Recent", amount=10_00, date=(_NOW - timedelta(days=2)).isoformat(),
            category="Food", account_id=acct.id,
        )
    )
    db_session.flush()
    assert is_lapsed(db_session, u.id, _NOW) is False
    saved = _enable("behavioral_landmark_enabled")
    try:
        summary = run_landmark_reentry(db_session, u.id, now=date(2026, 6, 1))
    finally:
        settings.behavioral_landmark_enabled = saved
    assert summary == {"engaged_skipped": 1, "created": 0}
    count = db_session.execute(
        text("SELECT count(*) FROM notifications WHERE type='landmark_reentry'")
    ).scalar()
    assert count == 0


def test_landmark_idempotent_per_period(db_session):
    u, acct = _user(db_session)
    db_session.add(
        ExpenseORM(
            title="Old", amount=10_00, date=(_NOW - timedelta(days=90)).isoformat(),
            category="Food", account_id=acct.id,
        )
    )
    db_session.flush()
    saved = _enable("behavioral_landmark_enabled")
    try:
        first = run_landmark_reentry(db_session, u.id, now=date(2026, 6, 1))
        second = run_landmark_reentry(db_session, u.id, now=date(2026, 6, 1))
    finally:
        settings.behavioral_landmark_enabled = saved
    assert first["created"] == 1
    assert second["created"] == 0


def test_landmark_flag_off_is_noop(db_session):
    u, _ = _user(db_session)
    summary = run_landmark_reentry(db_session, u.id, now=date(2026, 6, 1))
    assert summary["created"] == 0


def test_landmark_never_touches_streak_state(db_session):
    """The re-entry must not write any streak_state / game event — it only adds a
    notification. We assert no game_events row is produced by the job."""
    u, acct = _user(db_session)
    db_session.add(
        ExpenseORM(
            title="Old", amount=10_00, date=(_NOW - timedelta(days=90)).isoformat(),
            category="Food", account_id=acct.id,
        )
    )
    db_session.flush()
    before = db_session.execute(text("SELECT count(*) FROM game_events")).scalar()
    saved = _enable("behavioral_landmark_enabled")
    try:
        run_landmark_reentry(db_session, u.id, now=date(2026, 6, 1))
    finally:
        settings.behavioral_landmark_enabled = saved
    after = db_session.execute(text("SELECT count(*) FROM game_events")).scalar()
    assert after == before  # streak machine untouched


# ── POSTGRES: the escalation job binds per-user RLS tenant context and READS ───


@pytest.mark.skipif(not _PG, reason="RLS is Postgres-only; set TEST_DATABASE_URL to Postgres")
def test_escalation_job_sets_tenant_and_reads_rules_under_rls(_engine):
    """The B1 RLS guard: as a NON-superuser app_user with the real tenant policies
    ENABLED, the W7 escalation job must bind each user's tenant context before reading
    — otherwise it reads ZERO rules (the silent no-op) and bumps nothing. Proves the
    per-user set_tenant lets the job actually read the user's rules."""
    _TABLES = ("rules", "goals", "accounts", "expenses", "income", "notifications")

    with Session(_engine) as s:
        u, _acct = _user(s, balance=10_000_00)
        g = _goal(s, u.id)
        _allocate_rule(
            s, u.id, g.id,
            {"amount": 50, "escalation": {"step_amount": 25, "max_amount": 200}},
        )
        s.commit()
        user_id = u.id

    with _engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='app_user') "
                "THEN CREATE ROLE app_user NOSUPERUSER NOLOGIN; END IF; END $$"
            )
        )
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app_user"))
        for tbl in _TABLES:
            enable_rls(conn, tbl)
            conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO app_user"))
        conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user"))

    try:
        with Session(_engine) as s:
            s.execute(text("SET LOCAL ROLE app_user"))
            # SANITY: with NO tenant context, RLS fails closed — zero rules (the trap).
            assert s.execute(text("SELECT count(*) FROM rules")).scalar() == 0

            saved = settings.behavioral_escalation_enabled
            try:
                settings.behavioral_escalation_enabled = True
                set_tenant(s, user_id)
                # With tenant bound, the SAME query now sees the rule (NOT zero).
                assert s.execute(text("SELECT count(*) FROM rules")).scalar() == 1
                summary = run_escalation(s, user_id, now=_NOW)
                assert summary["bumped"] == 1
                row = s.execute(
                    text("SELECT action_params FROM rules WHERE user_id = :uid"),
                    {"uid": user_id},
                ).scalar()
                params = row if isinstance(row, dict) else json.loads(row)
                assert params["amount"] == 75
            finally:
                settings.behavioral_escalation_enabled = saved
            s.rollback()
    finally:
        with _engine.begin() as conn:
            for tbl in _TABLES:
                conn.execute(text(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation ON {tbl}"))
                conn.execute(text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY"))
                conn.execute(text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY"))
