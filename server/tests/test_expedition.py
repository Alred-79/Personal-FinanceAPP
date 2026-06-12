"""v4 package 08 — the Expedition.

Map generation (acts from confident income, weekly skeleton otherwise, bills as
nodes, rest windows, slack-gated forks), snapshot immutability, the date-
stripping scoring property (the no-timing-bonus guard), terrain ranking,
prestige sub-linearity + modest-month guarantee + idempotence, failure→story,
draft-template recommendation-word scan, and integrity.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from server.src.db.models import (
    Account as AccountORM,
    Income as IncomeORM,
    Expense as ExpenseORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.expedition import (
    RunService,
    ScoreInputs,
    generate_map,
    mint_prestige,
    rank_modifiers,
    score_run,
)
from server.tests.integrity import finance_tables_fingerprint

MONTH = "2026-06"


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="exp", full_name="Exp U", email="exp@x.com",
                   hashed_password="x", savings_percent=0)
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=200_00, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


def _income(db, acct, title, date, recurrence):
    db.add(IncomeORM(title=title, amount=200_00, date=date, category="Work",
                     recurrence=recurrence, account_id=acct.id))
    db.flush()


def _bill(db, acct, title, cents, date, category="Streaming"):
    db.add(ExpenseORM(title=title, amount=cents, date=date, category=category,
                      recurrence="monthly", account_id=acct.id))
    db.flush()


# ── 1: acts from confident income / weekly skeleton ──────────────────────


def test_two_confident_paychecks_make_income_acts(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _income(db_session, acct, "Pay1", "2026-06-06", "biweekly")
    _income(db_session, acct, "Pay2", "2026-06-20", "biweekly")
    m = generate_map(db_session, _u(user), MONTH)
    assert len(m.acts) == 3  # two boundaries → three acts


def test_irregular_income_falls_to_weekly_skeleton(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # Gig income with NO recurrence → low confidence → weekly skeleton.
    db_session.add(IncomeORM(title="Gig", amount=50_00, date="2026-06-10",
                             category="Work", recurrence=None, account_id=acct.id))
    db_session.flush()
    m = generate_map(db_session, _u(user), MONTH)
    assert len(m.acts) == 4  # weekly skeleton


def test_one_confident_stream_is_weekly_skeleton(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _income(db_session, acct, "Pay", "2026-06-06", "monthly")  # single in-month
    m = generate_map(db_session, _u(user), MONTH)
    assert len(m.acts) == 4  # the <2 rule


# ── 2: rest windows ──────────────────────────────────────────────────────


def test_rest_windows_precede_top_obligations(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _bill(db_session, acct, "Rent", 120_000, "2026-06-15", "Rent")
    m = generate_map(db_session, _u(user), MONTH)
    rest = sorted(n.day for n in m.nodes if n.kind == "rest")
    # K=2 days before the 15th → the 13th and 14th.
    assert "2026-06-13" in rest and "2026-06-14" in rest


# ── 4-5: snapshot immutability + determinism ─────────────────────────────


def test_map_is_deterministic(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _income(db_session, acct, "Pay1", "2026-06-06", "biweekly")
    _bill(db_session, acct, "Rent", 120_000, "2026-06-01", "Rent")
    a = generate_map(db_session, _u(user), MONTH).to_json()
    b = generate_map(db_session, _u(user), MONTH).to_json()
    assert a == b


def test_map_json_is_immutable_at_db_level(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    run = RunService(db_session).draft(_u(user), MONTH)
    # Attempting to UPDATE map_json must be aborted by the trigger.
    with pytest.raises(Exception):
        db_session.execute(
            text("UPDATE runs SET map_json='{}' WHERE id=:i"), {"i": run.id}
        )
        db_session.flush()
    db_session.rollback()


def test_overlay_changes_do_not_touch_snapshot(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    svc = RunService(db_session)
    run = svc.draft(_u(user), MONTH)
    snapshot = run.map_json
    svc.set_overlay(_u(user), MONTH, "defeat_by_date", "2026-09-01")
    db_session.refresh(run)
    assert run.map_json == snapshot  # unchanged
    assert json.loads(run.overlay_json)["defeat_by_date"] == "2026-09-01"


# ── 6: terrain ranking ───────────────────────────────────────────────────


def test_dining_heavy_month_offers_hearthkeeper(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _bill(db_session, acct, "Dinners", 80_000, "2026-06-10", "Dining")
    offered = rank_modifiers(db_session, _u(user), MONTH)
    assert "hearthkeeper" in offered and len(offered) == 3


# ── 9: draft templates have no recommendation words ──────────────────────


def test_fork_options_have_no_recommendation_words(db_session, user_acct):
    from server.src.services.game.expedition import _fork_options

    banned = ("best", "should", "recommend")
    for fork in _fork_options():
        text_blob = json.dumps(fork).lower()
        for w in banned:
            assert w not in text_blob


# ── 13: the date-stripping property (the no-timing-bonus guard) ──────────


def test_score_ignores_day_ordering():
    verdicts = ["GREEN"] * 15 + ["MISS"] * 5 + ["GRAY"] * 8
    all_early = verdicts[:]               # imagine all GREENs at month start
    all_late = list(reversed(verdicts))   # …vs all at month end
    assert score_run(ScoreInputs(all_early, 2, 3, 4, 10)) == \
        score_run(ScoreInputs(all_late, 2, 3, 4, 10))


def test_gray_excluded_from_denominator():
    # 5 GREEN, 5 MISS, +90 GRAY → ratio is 0.5, GRAY must not dilute it.
    s = score_run(ScoreInputs(["GREEN"] * 5 + ["MISS"] * 5 + ["GRAY"] * 90, 0, 0, 0, 0))
    assert s["green_ratio"] == 0.5


# ── 15: prestige ─────────────────────────────────────────────────────────


def test_prestige_is_sublinear():
    # Doubling the score grows prestige by LESS than 2x (sqrt curve). At score
    # 0.5 → 1.0 (a 2x jump), prestige goes 7 → 10, and 10 < 14.
    low = mint_prestige(0.5, 2)
    high = mint_prestige(1.0, 2)
    assert high < 2 * low


def test_modest_month_guarantee():
    assert mint_prestige(0.0, 1) >= 1  # >=1 GREEN week → >=1 prestige


def test_prestige_minted_once_per_month_idempotent(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    svc = RunService(db_session)
    svc.draft(_u(user), MONTH)
    si = ScoreInputs(["GREEN"] * 10, 1, 1, 4, 5)
    svc.seal(_u(user), MONTH, si)
    svc.seal(_u(user), MONTH, si)  # replay
    from server.src.db.models import GameEvent

    minted = db_session.query(GameEvent).filter(
        GameEvent.type == "PrestigeMinted").count()
    assert minted == 1


# ── 16: failure → story (counter-modifier, no tightening) ────────────────


def test_unmet_objective_adds_counter_modifier(db_session, user_acct):
    user, _ = user_acct
    svc = RunService(db_session)
    pool = svc.next_month_counter_modifiers(["dining"])
    assert any(p["key"] == "hearthkeeper" and p["counter"] for p in pool)


# ── 22: integrity ────────────────────────────────────────────────────────


def test_fingerprint_unchanged_across_run_lifecycle(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _income(db_session, acct, "Pay1", "2026-06-06", "biweekly")
    _bill(db_session, acct, "Rent", 120_000, "2026-06-01", "Rent")
    before = finance_tables_fingerprint(db_session)
    svc = RunService(db_session)
    svc.draft(_u(user), MONTH)
    svc.seal(_u(user), MONTH, ScoreInputs(["GREEN"] * 8 + ["MISS"] * 2, 1, 2, 3, 5))
    after = finance_tables_fingerprint(db_session)
    assert before == after  # runs/score never touch financial-truth tables
