"""v4 package 05 — the daily skeleton.

Green-day verdicts (GRAY is sacred), the streak machine (no 'broken' state by
construction), wards (auto-applied, post-hoc notice), revival, the daily verb
scheduler, the overnight tick (XP only, capped), basic Grace, and the
integrity/rebuild proof that streak_state is a pure fold of the log.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from server.src.db.models import (
    Account as AccountORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game.daily import (
    DailyService,
    GREEN,
    GRAY,
    MISS,
    REBUILDING,
    ACTIVE,
    REVIVING,
    WARD_CAP,
    DayInputs as DI,
    streak_view,
    verdict_for_day,
    _state,
    _put,
    register_daily_folds,
)
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.game.rebuild import rebuild_projection
from server.tests.integrity import finance_tables_fingerprint

AS_OF = date(2026, 6, 1)


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="day", full_name="Day U", email="day@x.com",
                   hashed_password="x", savings_percent=0)
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=300_00, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


def _close(db_session, user, day, verdict):
    """Directly emit a DayClosed with a chosen verdict (drives the fold)."""
    record_events(db_session, [GameEventDraft(
        stream="player", type="DayClosed",
        payload={"date": day.isoformat(), "verdict": verdict},
        idempotency_key=f"day:{user.id}:{day.isoformat()}",
    )])
    db_session.flush()


# ── 1: green-day verdict matrix ──────────────────────────────────────────


def test_verdict_matrix():
    # under-budget + positive STS = GREEN
    assert verdict_for_day(DI(10, False, True, False, False, False, False)) == GREEN
    # over discretionary = MISS
    assert verdict_for_day(DI(10, True, True, False, False, False, False)) == MISS
    # essentials can't MISS: discretionary fine even if STS positive → GREEN
    assert verdict_for_day(DI(50, False, True, False, False, False, False)) == GREEN
    # sync gap = GRAY (even if over)
    assert verdict_for_day(DI(-5, True, True, False, False, True, False)) == GRAY
    # low confidence = GRAY
    assert verdict_for_day(DI(-5, True, True, False, True, False, False)) == GRAY
    # grace active = GRAY
    assert verdict_for_day(DI(-5, True, True, False, False, False, True)) == GRAY
    # no data = GRAY
    assert verdict_for_day(DI(10, False, False, False, False, False, False)) == GRAY
    # pending-only = GRAY
    assert verdict_for_day(DI(10, False, True, True, False, False, False)) == GRAY


def test_negative_sts_is_miss():
    assert verdict_for_day(DI(-1, False, True, False, False, False, False)) == MISS


# ── 2: idempotent day close ──────────────────────────────────────────────


def test_day_close_is_idempotent(db_session, user_acct):
    user, _ = user_acct
    _close(db_session, user, AS_OF, GREEN)
    _close(db_session, user, AS_OF, GREEN)  # re-run same day
    assert _state(db_session)["current"] == 1


# ── streak machine (4-7) ─────────────────────────────────────────────────


def test_five_green_makes_streak_five(db_session, user_acct):
    user, _ = user_acct
    for i in range(5):
        _close(db_session, user, AS_OF + timedelta(days=i), GREEN)
    v = streak_view(db_session)
    assert v["current"] == 5 and v["best"] == 5 and v["status"] == ACTIVE


def test_miss_with_ward_consumes_ward_streak_intact(db_session, user_acct):
    user, _ = user_acct
    for i in range(5):
        _close(db_session, user, AS_OF + timedelta(days=i), GREEN)
    # grant a ward directly
    st = _state(db_session); st["wards"] = 1; _put(db_session, st)
    _close(db_session, user, AS_OF + timedelta(days=5), MISS)
    v = streak_view(db_session)
    assert v["current"] == 5 and v["wards"] == 0 and v["status"] == ACTIVE


def test_miss_without_ward_goes_rebuilding_best_preserved(db_session, user_acct):
    user, _ = user_acct
    for i in range(5):
        _close(db_session, user, AS_OF + timedelta(days=i), GREEN)
    _close(db_session, user, AS_OF + timedelta(days=5), MISS)
    v = streak_view(db_session)
    assert v["status"] == REBUILDING and v["best"] == 5 and v["current"] == 0


def test_no_broken_state_exists(db_session, user_acct):
    user, _ = user_acct
    _close(db_session, user, AS_OF, GREEN)
    _close(db_session, user, AS_OF + timedelta(days=1), MISS)
    # The only states are active|rebuilding|reviving — never 'broken'.
    assert _state(db_session)["status"] in (ACTIVE, REBUILDING, REVIVING)


def test_endowed_restart_first_green_is_day_one(db_session, user_acct):
    user, _ = user_acct
    _close(db_session, user, AS_OF, GREEN)
    _close(db_session, user, AS_OF + timedelta(days=1), MISS)  # → rebuilding
    _close(db_session, user, AS_OF + timedelta(days=2), GREEN)  # first green back
    v = streak_view(db_session)
    assert v["current"] == 1 and v["status"] == ACTIVE


def test_two_misses_one_ward_no_double_spend(db_session, user_acct):
    user, _ = user_acct
    for i in range(3):
        _close(db_session, user, AS_OF + timedelta(days=i), GREEN)
    st = _state(db_session); st["wards"] = 1; _put(db_session, st)
    _close(db_session, user, AS_OF + timedelta(days=3), MISS)  # ward
    _close(db_session, user, AS_OF + timedelta(days=4), MISS)  # rebuilding
    v = streak_view(db_session)
    assert v["wards"] == 0 and v["status"] == REBUILDING


# ── 8: ward replenish only from XP-bearing money actions ─────────────────


def test_wards_replenish_only_from_xp_bearing(db_session, user_acct):
    user, _ = user_acct
    register_daily_folds()
    # 1 AllocationMade = 20 XP; threshold is 50 → need 3 for one ward.
    for i in range(3):
        record_events(db_session, [GameEventDraft(
            stream="player", type="AllocationMade", payload={},
            idempotency_key=f"alloc:{i}")])
    db_session.flush()
    assert _state(db_session)["wards"] == 1
    # Cap at 2 no matter how many more.
    for i in range(20):
        record_events(db_session, [GameEventDraft(
            stream="player", type="AllocationMade", payload={},
            idempotency_key=f"alloc2:{i}")])
    db_session.flush()
    assert _state(db_session)["wards"] <= WARD_CAP


def test_consistency_verbs_never_replenish_wards(db_session, user_acct):
    user, _ = user_acct
    register_daily_folds()
    for i in range(20):
        record_events(db_session, [GameEventDraft(
            stream="player", type="ConsistencyVerb",
            payload={"day": f"2026-06-{i+1:02d}"},
            idempotency_key=f"verb:{i}")])
    db_session.flush()
    assert _state(db_session)["wards"] == 0


# ── revival (9-10) ───────────────────────────────────────────────────────


def test_revival_three_green_with_gray_pause_completes(db_session, user_acct):
    user, _ = user_acct
    # Set up a reviving state with best=34.
    st = _state(db_session)
    st.update({"status": REVIVING, "best": 34, "current": 0,
               "revival": {"green": 0, "offered_on": AS_OF.isoformat()}})
    _put(db_session, st)
    _close(db_session, user, AS_OF, GREEN)
    _close(db_session, user, AS_OF + timedelta(days=1), GREEN)
    _close(db_session, user, AS_OF + timedelta(days=2), GRAY)   # pauses
    _close(db_session, user, AS_OF + timedelta(days=3), GREEN)  # 3rd green
    v = streak_view(db_session)
    assert v["current"] == 34 and v["status"] == ACTIVE


def test_revival_miss_ends_quietly(db_session, user_acct):
    user, _ = user_acct
    st = _state(db_session)
    st.update({"status": REVIVING, "best": 34, "current": 0,
               "revival": {"green": 1, "offered_on": AS_OF.isoformat()}})
    _put(db_session, st)
    _close(db_session, user, AS_OF, MISS)
    v = streak_view(db_session)
    assert v["status"] == REBUILDING and not v["reviving"]


# ── verb scheduler (11-14) ───────────────────────────────────────────────


def test_verb_at_most_one_and_selection(db_session, user_acct):
    user, _ = user_acct
    svc = DailyService(db_session)
    u = _u(user)
    # big bill 5 days out → scout
    assert svc.pick_verb(u, AS_OF, big_bill_days_out=5) == "scout_bill"
    # confidence dropped → confirm_forecast
    assert svc.pick_verb(u, AS_OF, confidence_dropped=True) == "confirm_forecast"
    # slack → what_if
    assert svc.pick_verb(u, AS_OF, slack_available=True) == "what_if"
    # otherwise → tag
    assert svc.pick_verb(u, AS_OF) == "worth_it_tag"


def test_strain_mode_only_confirm_forecast(db_session, user_acct):
    user, _ = user_acct
    svc = DailyService(db_session)
    # even with a big bill + slack, strain forces confirm_forecast only
    assert svc.pick_verb(_u(user), AS_OF, strain_mode=True,
                         big_bill_days_out=5, slack_available=True) == "confirm_forecast"


def test_completed_verb_emits_one_capped_consistency(db_session, user_acct):
    user, _ = user_acct
    register_daily_folds()
    svc = DailyService(db_session)
    from server.src.services.game.stats import player_xp
    before = player_xp(db_session)["xp"]
    svc.complete_verb(_u(user), AS_OF, "worth_it_tag")
    after = player_xp(db_session)["xp"]
    from server.src.services.game.xp import CONSISTENCY_DAILY_CAP
    assert 0 < after - before <= CONSISTENCY_DAILY_CAP


# ── tick (15-16) ─────────────────────────────────────────────────────────


def test_tick_caps_at_seven_days_and_collect_reveals(db_session, user_acct):
    user, _ = user_acct
    register_daily_folds()
    svc = DailyService(db_session)
    u = _u(user)
    for i in range(10):  # accrue 10 days
        svc.accrue_tick(u, AS_OF + timedelta(days=i))
    from server.src.services.game.daily import TICK_UNCOLLECTED_CAP_DAYS, TICK_PER_DAY
    assert _state(db_session).get("tick_pending", 0) == TICK_UNCOLLECTED_CAP_DAYS * TICK_PER_DAY
    # collect reveals the total and awards nothing extra
    from server.src.services.game.stats import player_xp
    xp_before = player_xp(db_session)["xp"]
    collected = svc.collect_tick(u)
    assert collected == TICK_UNCOLLECTED_CAP_DAYS * TICK_PER_DAY
    assert player_xp(db_session)["xp"] == xp_before
    assert _state(db_session)["tick_pending"] == 0


# ── grace (17-19) ────────────────────────────────────────────────────────


def test_grace_applies_once_and_grants_no_xp(db_session, user_acct):
    user, acct = user_acct
    register_daily_folds()
    from server.src.services.game.grace import GraceService, is_active
    from server.src.services.game.stats import player_xp
    # Force a trigger: STS below floor by draining balance via a huge bill is
    # finance-truth; instead set balance negative-ish by zero balance + buffer.
    acct.balance = -100  # negative balance → STS below floor
    db_session.flush()
    xp_before = player_xp(db_session)["xp"]
    svc = GraceService(db_session)
    assert svc.apply_if_triggered(_u(user), AS_OF) is True
    assert is_active(db_session)
    # idempotent: applying again doesn't double the grace ward
    wards = _state(db_session)["grace_wards"]
    svc.apply_if_triggered(_u(user), AS_OF)
    assert _state(db_session)["grace_wards"] == wards
    # grace grants no XP
    assert player_xp(db_session)["xp"] == xp_before


def test_grace_ward_equips_beyond_cap(db_session, user_acct):
    user, acct = user_acct
    register_daily_folds()
    from server.src.services.game.grace import GraceService
    # fill normal wards to cap
    st = _state(db_session); st["wards"] = WARD_CAP; _put(db_session, st)
    acct.balance = -100
    db_session.flush()
    GraceService(db_session).apply_if_triggered(_u(user), AS_OF)
    s = _state(db_session)
    assert s["grace_wards"] >= 1  # equipped beyond the normal cap


def test_grace_day_is_gray():
    # A grace-active day always reads GRAY regardless of the money state.
    assert verdict_for_day(DI(-99, True, True, False, False, False, True)) == GRAY


# ── guardrails: banned words + no money in streak/tick copy ───────────────

import json as _json
from pathlib import Path as _Path

_TERMS_DIR = _Path(__file__).resolve().parents[2] / "client" / "src" / "terms"
_BANNED = ("broken", "lost", "dead", "failed", "behind", "worse")
# transaction verbs a streak template must never contain (no "spend less to…")
_TXN_VERBS = ("spend", "buy", "purchase", "pay ")


def _load_terms(mode):
    return _json.loads((_TERMS_DIR / f"terms.{mode}.json").read_text())


def test_streak_templates_have_no_banned_words_or_txn_verbs():
    for mode in ("off", "ambient", "full"):
        terms = _load_terms(mode)
        for key, value in terms.items():
            if not (key.startswith("streak") or key.startswith("ward")):
                continue
            low = value.lower()
            for w in _BANNED:
                assert w not in low, f"banned word {w!r} in {mode}:{key} = {value!r}"
            for v in _TXN_VERBS:
                assert v not in low, f"txn verb {v!r} in {mode}:{key} = {value!r}"


def test_tick_templates_carry_no_currency_symbol():
    for mode in ("off", "ambient", "full"):
        terms = _load_terms(mode)
        for key, value in terms.items():
            if key.startswith("tick"):
                assert "$" not in value and "€" not in value, f"currency in {mode}:{key}"


# ── 20: integrity + rebuild ──────────────────────────────────────────────


def test_fingerprint_unchanged_and_rebuild_reproduces(db_session, user_acct):
    user, _ = user_acct
    register_daily_folds()
    before = finance_tables_fingerprint(db_session)
    # Earn a ward via real events (3 AllocationMade = 60 XP ≥ 50 threshold), so
    # the ward is part of the LOG and survives a rebuild. Seeding via _put would
    # not — rebuild is a pure fold of the event log, by design.
    for i in range(3):
        record_events(db_session, [GameEventDraft(
            stream="player", type="AllocationMade", payload={},
            idempotency_key=f"fp-alloc:{i}")])
    db_session.flush()
    assert _state(db_session)["wards"] == 1
    verdicts = [GREEN, GREEN, GRAY, GREEN, MISS, GREEN, MISS, GREEN]
    for i, v in enumerate(verdicts):
        _close(db_session, user, AS_OF + timedelta(days=i), v)
    live = dict(_state(db_session))
    after = finance_tables_fingerprint(db_session)
    assert before == after  # Law 1: game code never wrote financial truth

    # Rebuild streak_state from the log and compare the meaningful fields.
    rebuild_projection(db_session, "streak_state")
    rebuilt = _state(db_session)
    for k in ("status", "current", "best", "wards", "grace_wards"):
        assert rebuilt[k] == live[k], f"rebuild mismatch on {k}"


# ── regression: revival is reachable from production code ────────────────


def test_revival_offer_transitions_rebuilding_to_reviving(db_session, user_acct):
    user, _ = user_acct
    svc = DailyService(db_session)
    # Set up an eligible dead streak: best 34, dead 40 days ago, rebuilding.
    st = _state(db_session)
    st.update({"status": REBUILDING, "best": 34, "current": 0,
               "dead_on": (AS_OF - timedelta(days=40)).isoformat()})
    _put(db_session, st)
    assert svc.revival_eligible(AS_OF) is True
    assert svc.offer_revival(_u(user), AS_OF) is True
    assert _state(db_session)["status"] == REVIVING
    # Three green days restore the best run.
    for i in range(3):
        _close(db_session, user, AS_OF + timedelta(days=i), GREEN)
    assert streak_view(db_session)["current"] == 34


def test_revival_eligibility_gate(db_session, user_acct):
    user, _ = user_acct
    svc = DailyService(db_session)
    # best < 30 → not eligible.
    st = _state(db_session)
    st.update({"status": REBUILDING, "best": 20, "current": 0,
               "dead_on": (AS_OF - timedelta(days=10)).isoformat()})
    _put(db_session, st)
    assert svc.revival_eligible(AS_OF) is False
    # dead too long (>90d) → not eligible.
    st["best"] = 40
    st["dead_on"] = (AS_OF - timedelta(days=120)).isoformat()
    _put(db_session, st)
    assert svc.revival_eligible(AS_OF) is False
    # active streak → not eligible.
    st["status"] = ACTIVE
    _put(db_session, st)
    assert svc.revival_eligible(AS_OF) is False


def test_revival_offer_not_repeated_after_failed_attempt(db_session, user_acct):
    user, _ = user_acct
    svc = DailyService(db_session)
    st = _state(db_session)
    st.update({"status": REBUILDING, "best": 34, "current": 0,
               "dead_on": (AS_OF - timedelta(days=40)).isoformat()})
    _put(db_session, st)
    svc.offer_revival(_u(user), AS_OF)
    _close(db_session, user, AS_OF, MISS)  # revival ends quietly
    # The quarter is now consumed — no immediate re-offer.
    assert svc.revival_eligible(AS_OF + timedelta(days=1)) is False


# ── regression: grace ward is rebuildable ────────────────────────────────


def test_grace_ward_survives_rebuild(db_session, user_acct):
    user, acct = user_acct
    register_daily_folds()
    from server.src.services.game.grace import GraceService
    from server.src.services.game.rebuild import rebuild_projection

    acct.balance = -100  # force a Grace trigger
    db_session.flush()
    GraceService(db_session).apply_if_triggered(_u(user), AS_OF)
    live = _state(db_session)["grace_wards"]
    assert live >= 1
    # Rebuild streak_state from the log: the grace ward must reproduce (it's now
    # folded from GraceApplied, not a direct mutation that the log can't replay).
    rebuild_projection(db_session, "streak_state")
    assert _state(db_session)["grace_wards"] == live


# ── regression: ward-cap clamp doesn't destroy earned wards ──────────────


def test_grace_ward_does_not_destroy_earned_wards(db_session, user_acct):
    user, _ = user_acct
    register_daily_folds()
    # Earn 2 wards via XP-bearing events (3 AllocationMade = 60 XP, but cap is 2).
    for i in range(6):
        record_events(db_session, [GameEventDraft(
            stream="player", type="AllocationMade", payload={},
            idempotency_key=f"wclamp-alloc:{i}")])
    db_session.flush()
    earned = _state(db_session)["wards"]
    assert earned >= 1
    # Add a grace ward, then a harmless XP event. The earned ward must NOT drop.
    st = _state(db_session); st["grace_wards"] = 1; _put(db_session, st)
    record_events(db_session, [GameEventDraft(
        stream="player", type="AllocationMade", payload={},
        idempotency_key="wclamp-after")])
    db_session.flush()
    assert _state(db_session)["wards"] == earned  # not silently clamped down
