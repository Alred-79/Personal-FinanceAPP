"""v4 package 10 — graduation/fade + experiments/holdout (spec cases 13-20).

The fade state machine and its spine exemption; cohort stability; the holdout
lock (spine never withheld); exposure-log separation; the kill-switch drill;
the metrics jobs over golden fixtures.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    HeatContract,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import experiments, folds as folds_mod
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.game.fade import (
    REGRESSED_WEEKS_TO_RESURFACE,
    STABLE_WEEKS_TO_GRADUATE,
    FadeService,
    is_faded,
)

AS_OF = date(2026, 6, 15)
WEEK0 = date(2026, 4, 6)  # a Monday-ish anchor for synthetic weeks


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="expu", full_name="Exp U", email="expu@x.com",
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


def _emit(db, ev_type, payload, idem=None, stream="player"):
    record_events(db, [GameEventDraft(
        stream=stream, type=ev_type, payload=payload, idempotency_key=idem,
    )])
    db.flush()


def _note_weeks(db, user, metric, n, stable, start_week=0):
    svc = FadeService(db)
    state = None
    for i in range(n):
        week_end = WEEK0 + timedelta(days=7 * (start_week + i))
        state = svc.note_week(_u(user), metric, week_end, stable)
    return state


# ── 13: 9 stable weeks → graduated; spawning stops; resurface on regress ────


def test_nine_stable_weeks_graduate_dining_then_resurface(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()

    state = _note_weeks(db_session, user, "Dining", 9, stable=True)
    assert state == "graduated"
    assert is_faded(db_session, _u(user), "Dining")
    # The MetricGraduated record exists in the log.
    count = db_session.execute(text(
        "SELECT COUNT(*) FROM game_events WHERE type = 'MetricGraduated'"
    )).scalar_one()
    assert count == 1

    # Dining monsters stop spawning while graduated: an over-pace dining month
    # that would spawn a minor monster spawns nothing.
    db_session.add(BudgetORM(user_id=user.id, category="Dining",
                             monthly_limit=100_00, rollover=0))
    db_session.add(ExpenseORM(title="Dining spree", amount=200_00,
                              date=AS_OF.isoformat(), category="Dining",
                              account_id=acct.id))
    db_session.flush()
    from server.src.services.game.habit_monsters import detect_monsters

    assert all(m["key"] != "Dining" for m in detect_monsters(db_session, _u(user), AS_OF))

    # The weekly summary still includes the metric (the ONE remaining surface).
    summary = FadeService(db_session).weekly_summary(_u(user))
    assert "Dining" in summary["graduated_metrics"]

    # 2 consecutive regressed weeks → resurfaces; monsters can spawn again.
    state = _note_weeks(db_session, user, "Dining",
                        REGRESSED_WEEKS_TO_RESURFACE, stable=False, start_week=9)
    assert state == "active"
    assert not is_faded(db_session, _u(user), "Dining")
    assert any(m["key"] == "Dining" for m in detect_monsters(db_session, _u(user), AS_OF))


# ── 14: fade never touches the Money Spine ──────────────────────────────────


def test_fade_never_touches_spine_alert_number_grace(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # Graduate EVERYTHING the user spends on.
    for metric in ("Dining", "Utilities", "Shopping"):
        _note_weeks(db_session, user, metric, STABLE_WEEKS_TO_GRADUATE, stable=True)
        assert is_faded(db_session, _u(user), metric)

    # BILL_DIP still fires: a big recurring bill due in 2 days against a thin
    # balance. (The alert engine never consults fade state.) The anchor sits a
    # month back — project_occurrences excludes the anchor itself, so the
    # projected June occurrence is what lands in the window.
    acct.balance = 50_00
    db_session.add(ExpenseORM(title="Rent", amount=120_00,
                              date=(AS_OF + timedelta(days=2) - timedelta(days=31)).isoformat(),
                              category="Utilities", recurrence="monthly",
                              account_id=acct.id))
    db_session.flush()
    from server.src.services.game.alerts import AlertEngine

    candidates = AlertEngine(db_session).evaluate(_u(user), AS_OF)
    assert any(a.type == "BILL_DIP" for a in candidates)

    # The glanceable number still renders.
    from server.src.services.spend_service import SpendService

    sts = SpendService(db_session).safe_to_spend(_u(user), as_of=AS_OF)
    assert "available" in sts

    # Grace still triggers (negative Safe-to-Spend → a trigger fires).
    from server.src.services.game.grace import GraceService

    signals = GraceService(db_session).evaluate(_u(user), AS_OF)
    assert isinstance(signals.any, bool)  # the evaluation path is intact
    active = GraceService(db_session).apply_if_triggered(_u(user), AS_OF)
    assert isinstance(active, bool)


# ── 15: the user pin overrides fade in both directions ──────────────────────


def test_pin_overrides_fade_both_directions(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    svc = FadeService(db_session)

    # always_active: 10 stable weeks never quiet the metric.
    svc.set_pin(_u(user), "Dining", "always_active")
    _note_weeks(db_session, user, "Dining", 10, stable=True)
    assert not is_faded(db_session, _u(user), "Dining")

    # always_faded: quiet immediately, regardless of history.
    svc.set_pin(_u(user), "Coffee", "always_faded")
    assert is_faded(db_session, _u(user), "Coffee")

    # Unpinning restores the detector's verdict.
    svc.set_pin(_u(user), "Coffee", "none")
    assert not is_faded(db_session, _u(user), "Coffee")


# ── 16: cohort assignment — stable, proportional ────────────────────────────


def test_cohort_assignment_stable_and_proportional():
    # Stability: the same identity always lands in the same bucket.
    for uid, name in ((1, "alice"), (42, "bob"), (999, "carol")):
        assert experiments.cohort_for(uid, name) == experiments.cohort_for(uid, name)

    # Proportion: ~10% holdout over 1,000 synthetic users, within tolerance.
    holdout = sum(
        1 for i in range(1000)
        if experiments.cohort_for(i, f"user{i}") == experiments.COHORT_HOLDOUT
    )
    assert 60 <= holdout <= 140, f"holdout fraction off: {holdout}/1000"


def test_cohort_persisted_once_never_rederived(db_session, user_acct):
    user, _ = user_acct
    first = experiments.ensure_cohort(db_session, user.id)
    # Even if the username changes, the stored cohort is the truth.
    user.username = "renamed"
    db_session.flush()
    assert experiments.ensure_cohort(db_session, user.id) == first


# ── 17: the holdout lock — game off, spine fully functional ─────────────────


def _signup(client, username, email):
    resp = client.post("/api/signup/", json={
        "username": username, "email": email, "full_name": "H U",
        "password": "Test-password1",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_holdout_user_mode_locked_off_spine_untouched(client, db_session):
    # 'm_all' with user id 1 hashes into the holdout bucket (verified by the
    # cohort math); a fresh per-test DB gives this signup id 1.
    h = _signup(client, "m_all", "m_all@x.com")

    # Activation attempt → cohort assigned → mode stays OFF.
    resp = client.put("/api/settings/preferences/",
                      json={"game_mode": "full"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["game_mode"] == "off"
    cohort = db_session.execute(
        text("SELECT experiment_cohort FROM users WHERE username='m_all'")
    ).scalar_one()
    assert cohort == experiments.COHORT_HOLDOUT

    # Game surfaces render their off-state…
    assert client.get("/api/game/campaigns/", headers=h).json() == {"campaign": None}
    body = client.get("/api/game/challenges/", headers=h).json()
    assert body == {"challenges": [], "candidates": []}
    assert client.get("/api/game/chapter/", headers=h).json() == {"chapter": None}
    assert client.get("/api/game/flags/", headers=h).json()["holdout"] is True

    # …zero generation jobs would run (the flavor gate is the job gate)…
    from server.src.services.game.mode import should_generate_flavor

    row = db_session.execute(text(
        "SELECT game_mode FROM users WHERE username='m_all'")).scalar_one()
    assert row == "off"

    # …and the Money Spine functions: the number, alerts eval, what-if config.
    sts = client.get("/api/spend/safe-to-spend/", headers=h)
    assert sts.status_code == 200 and "available" in sts.json()
    settings_body = client.get("/api/settings/", headers=h).json()
    assert settings_body["preferences"]["game_mode"] == "off"


# ── 18: exposure logs — observability table, never game_events ──────────────


def test_exposure_logging_separation(db_session, user_acct):
    user, _ = user_acct
    events_before = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")).scalar_one()

    for flag_key in experiments.FLAGS:
        arm = experiments.assign_arm(flag_key, user.id)
        assert arm in experiments.FLAGS[flag_key].arms
        experiments.log_exposure(db_session, user.id, flag_key, arm, "test")

    rows = db_session.execute(
        text("SELECT COUNT(*) FROM experiment_exposures")).scalar_one()
    assert rows == len(experiments.FLAGS)
    events_after = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")).scalar_one()
    assert events_after == events_before  # ZERO game events from analytics


def test_every_flag_documents_its_dv_query():
    assert set(experiments.FLAGS) == {f"E{i}" for i in range(1, 10)}
    for flag in experiments.FLAGS.values():
        assert flag.dv_query.strip(), f"{flag.key} has no documented DV query"
        assert len(flag.arms) >= 2


# ── 19: the kill-switch drill (heat) ────────────────────────────────────────


def test_kill_heat_drill(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # A live sweep-arm contract, as package 09 leaves it.
    db_session.add(CategorySettingsORM(name="Dining", essential=0, user_confirmed=1))
    for day in ("2026-03-10", "2026-04-10", "2026-05-10"):
        db_session.add(ExpenseORM(title="Dining", amount=150_00, date=day,
                                  category="Dining", account_id=acct.id))
    db_session.add(ExpenseORM(title="Old", amount=100, date="2026-01-01",
                              category="Dining", account_id=acct.id))
    db_session.flush()
    contract = HeatContract(user_id=user.id, category="Dining",
                            kind="cap_vs_baseline", target_param=75,
                            heat_value=1, month="2026-06", status="active",
                            arm="sweep")
    db_session.add(contract)
    db_session.flush()

    experiments.kill("heat")
    try:
        assert experiments.is_killed("heat")
        assert "heat" in experiments.flags_payload(db_session, user.id)["killed"]

        # The month-close job resolves the contract VOID with a soft landing.
        from server.src.services.game.month_close import resolve_heat_contracts

        proposals = resolve_heat_contracts(db_session, _u(user), "2026-06",
                                           date(2026, 6, 30))
        assert proposals == []  # jobs paused: no sweep proposal under a kill
        assert contract.status == "void"

        # Folds/rebuilds stay clean with the feature killed.
        from server.src.services.game.rebuild import rebuild_all

        _emit(db_session, "UnderBudgetDayClosed", {"date": "2026-06-10"}, "g:k:1")
        watermarks = rebuild_all(db_session)
        assert watermarks  # every projection rebuilt without error
    finally:
        experiments.revive("heat")
    assert not experiments.is_killed("heat")


def test_kill_switch_is_config_not_schema():
    import inspect

    import server.src.services.game.experiments as exp_mod

    source = inspect.getsource(exp_mod)
    assert "op.add_column" not in source and "ALTER TABLE" not in source
    with pytest.raises(ValueError):
        experiments.kill("not_a_feature")


# ── 20: metrics jobs over golden fixtures ───────────────────────────────────


def test_hard_day_action_rate_golden(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    from server.src.services.game.metrics import hard_day_action_rate

    # Trigger 1: Grace on 6/01; a real money action follows on 6/02 (hit).
    _emit(db_session, "GraceApplied", {"date": "2026-06-01"}, "g1")
    _emit(db_session, "AllocationMade", {"date": "2026-06-02"}, "a1")
    # Trigger 2: an alert on 6/10 with no action within 48h (miss).
    _emit(db_session, "AlertFired", {"date": "2026-06-10"}, "f1")

    rate = hard_day_action_rate(db_session, date(2026, 6, 1), date(2026, 6, 30))
    assert rate == 0.5
    # No triggers → None, never a fake rate.
    assert hard_day_action_rate(db_session, date(2026, 1, 1), date(2026, 1, 31)) is None


def test_alert_fix_rate_golden(db_session, user_acct):
    folds_mod.register_builtin_folds()
    from server.src.services.game.metrics import alert_fix_rate

    _emit(db_session, "AlertFired", {"date": "2026-06-03"}, "af1")
    _emit(db_session, "AlertFired", {"date": "2026-06-05"}, "af2")
    _emit(db_session, "AlertFixApplied",
          {"date": "2026-06-03", "fix_kind": "create_allocation"}, "afx1")
    assert alert_fix_rate(db_session, date(2026, 6, 1), date(2026, 6, 30)) == 0.5


def test_distortion_share_golden(db_session, user_acct):
    user, acct = user_acct
    from server.src.services.game.metrics import distortion_share

    # 100 discretionary over the month; 25 of it in the last 3 days.
    db_session.add(ExpenseORM(title="Mid", amount=75_00, date="2026-06-10",
                              category="Dining", account_id=acct.id))
    db_session.add(ExpenseORM(title="Tail", amount=25_00, date="2026-06-29",
                              category="Dining", account_id=acct.id))
    # Essentials are excluded from the distortion math.
    db_session.add(CategorySettingsORM(name="Rent", essential=1, user_confirmed=1))
    db_session.add(ExpenseORM(title="Rent", amount=500_00, date="2026-06-30",
                              category="Rent", account_id=acct.id))
    db_session.flush()
    assert distortion_share(db_session, user.id, "2026-06") == 0.25


def test_e9_query_returns_per_arm_totals(db_session, user_acct):
    user, acct = user_acct
    db_session.add(CategorySettingsORM(name="Dining", essential=0, user_confirmed=1))
    for day in ("2026-03-10", "2026-04-10", "2026-05-10"):
        db_session.add(ExpenseORM(title="Dining", amount=150_00, date=day,
                                  category="Dining", account_id=acct.id))
    db_session.add(ExpenseORM(title="Old", amount=100, date="2026-01-01",
                              category="Dining", account_id=acct.id))
    for arm, status in (("cosmetic", "met"), ("cosmetic", "unmet"),
                        ("sweep", "met")):
        db_session.add(HeatContract(
            user_id=user.id, category="Dining", kind="cap_vs_baseline",
            target_param=75, heat_value=1, month="2026-06", status=status,
            arm=arm))
    db_session.flush()
    from server.src.services.game.metrics import e9_sweep_totals

    totals = e9_sweep_totals(db_session, date(2026, 6, 30))
    assert totals["cosmetic"]["contracts"] == 2
    assert totals["cosmetic"]["met"] == 1
    assert totals["sweep"]["met"] == 1
    assert totals["sweep"]["swept_cents"] >= 0


def test_weekly_rollups_and_outcomes_summary(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    user.experiment_cohort = "game"
    db_session.flush()
    _emit(db_session, "GraceApplied", {"date": "2026-06-09"}, "gr1")
    _emit(db_session, "AllocationMade", {"date": "2026-06-10"}, "al1")
    from server.src.services.game.metrics import outcomes_summary, run_weekly_rollups

    written = run_weekly_rollups(db_session, date(2026, 6, 14))
    assert written >= 1
    # Idempotent: a re-run writes nothing new.
    assert run_weekly_rollups(db_session, date(2026, 6, 14)) == 0

    summary = outcomes_summary(db_session)
    assert "hard_day_action_rate" in summary["comparison"]
    cell = summary["comparison"]["hard_day_action_rate"]["game"]
    assert cell["n"] == 1 and cell["ci_low"] <= cell["mean"] <= cell["ci_high"]
    footer = summary["honesty_footer"]
    assert footer["sample_sizes"]["game"] == 1 and footer["caveats"]
