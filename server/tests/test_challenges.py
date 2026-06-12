"""v4 package 10 — challenges (spec test cases 6-12).

T1 judged by code over POSTED events only; T2 awarded by the ENGINE from the
structured verdict (never the text); T3 cosmetic with no verification theater;
mandatory exits (graduation / soft landing); the StepBet anti-pattern is
structurally impossible.
"""

from __future__ import annotations

import inspect
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text

from server.src.db.models import (
    Account as AccountORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    Rule as RuleORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.challenges import (
    TIER_XP,
    ChallengeError,
    ChallengeService,
)
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.game.stats import player_xp
from server.tests.integrity import finance_tables_fingerprint

START = date(2026, 6, 1)  # challenge window start
END = START + timedelta(days=7)
AS_OF = date(2026, 6, 15)


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="chal", full_name="Chal U", email="chal@x.com",
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


def _confirmed_category(db, name, *, essential=0):
    db.add(CategorySettingsORM(name=name, essential=essential, user_confirmed=1))
    db.flush()


def _category_history(db, acct, category, monthly_cents=150_00):
    """3 prior months + an old entry → a confident baseline (heat's pattern)."""
    for day in ("2026-03-10", "2026-04-10", "2026-05-10"):
        db.add(ExpenseORM(title=category, amount=monthly_cents, date=day,
                          category=category, account_id=acct.id))
    db.add(ExpenseORM(title="Old", amount=100, date="2026-01-01",
                      category=category, account_id=acct.id))
    db.flush()


def _posted_txn_event(db, category, day, amount_cents=20_00, txn_id=None):
    """A POSTED transaction, as the sync pipeline records it."""
    txn_id = txn_id or f"tx-{category}-{day}"
    record_events(db, [GameEventDraft(
        stream="sync", type="TxnPosted",
        payload={"plaid_transaction_id": txn_id, "account_id": 1,
                 "kind": "expense", "amount_cents": amount_cents,
                 "category": category, "date": day},
        idempotency_key=f"plaid:{txn_id}:posted",
    )])
    db.flush()


def _offer_t1(db, user, category="Delivery"):
    return ChallengeService(db).offer(
        _u(user), "t1_category_free_week", category, START,
        params={"categories": [category]},
    )


# ── 6: T1 end-to-end — posted-only, full XP, graduation offer ───────────────


def test_t1_delivery_free_week_met_awards_full_xp(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    svc = ChallengeService(db_session)
    challenge = _offer_t1(db_session, user)

    xp_before = player_xp(db_session)["xp"]
    status = svc.judge_t1(_u(user), challenge)
    assert status == "met"
    assert player_xp(db_session)["xp"] == xp_before + TIER_XP[1]
    offer = svc.graduation_offer(challenge)
    assert offer["kind"] == "standing_rule" and offer["category"] == "Delivery"


def test_t1_one_posted_delivery_txn_fails_softly(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    challenge = _offer_t1(db_session, user)
    _posted_txn_event(db_session, "Delivery", (START + timedelta(days=2)).isoformat())

    xp_before = player_xp(db_session)["xp"]
    status = ChallengeService(db_session).judge_t1(_u(user), challenge)
    assert status == "soft_landed"
    assert player_xp(db_session)["xp"] == xp_before  # no award, no deduction


def test_t1_pending_txn_never_judges(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    challenge = _offer_t1(db_session, user)
    # A pending charge lands as a CRUD row but emits NO TxnPosted event (the
    # sync pipeline's rule) — the judge reads events, so it cannot see it.
    db_session.add(ExpenseORM(title="Pending delivery", amount=25_00,
                              date=(START + timedelta(days=3)).isoformat(),
                              category="Delivery", account_id=acct.id))
    db_session.flush()
    assert ChallengeService(db_session).judge_t1(_u(user), challenge) == "met"


# ── 7: a sync gap voids quietly (GRAY logic, pro-player) ────────────────────


def test_t1_sync_gap_voids_quietly_and_reoffers(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    challenge = _offer_t1(db_session, user)
    # A gap covering 2 of the 7 days.
    record_events(db_session, [
        GameEventDraft(stream="sync", type="SyncGapOpened",
                       payload={"account_id": acct.id,
                                "opened_at": (START + timedelta(days=2)).isoformat()}),
        GameEventDraft(stream="sync", type="SyncGapClosed",
                       payload={"account_id": acct.id,
                                "closed_at": (START + timedelta(days=3)).isoformat()}),
    ])
    db_session.flush()

    xp_before = player_xp(db_session)["xp"]
    events_before = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")).scalar_one()
    status = ChallengeService(db_session).judge_t1(_u(user), challenge)
    assert status == "void"
    assert player_xp(db_session)["xp"] == xp_before  # no award
    events_after = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")).scalar_one()
    assert events_after == events_before  # QUIET: no penalty, no event at all
    # Re-offer later works — a void never suppresses.
    again = _offer_t1(db_session, user)
    assert again.status == "active"


# ── 8: T2 — the engine awards from the structured verdict only ─────────────


def test_t2_structured_verdict_awards_reduced_xp_from_engine(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Streaming")
    _category_history(db_session, acct, "Streaming")
    svc = ChallengeService(db_session)
    challenge = svc.offer(_u(user), "t2_reference_check", "Streaming", START)

    references = [{"url": "https://example.com/pricing", "content": "tiers"}]
    verdict = {"met": True, "evidence_ref": "https://example.com/pricing",
               "text": "A cheaper tier exists."}
    xp_before = player_xp(db_session)["xp"]
    status = svc.resolve_t2(_u(user), challenge, verdict, references)
    assert status == "met"
    assert player_xp(db_session)["xp"] == xp_before + TIER_XP[2]

    # The award call site is the ENGINE module: the LLM/Tavily module is
    # structurally incapable of recording anything.
    from server.src.services.game import challenge_verdict

    source = inspect.getsource(challenge_verdict)
    assert "record_events" not in source
    assert "GameEventDraft" not in source


def test_t2_unresolvable_evidence_voids_with_no_award(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Streaming")
    _category_history(db_session, acct, "Streaming")
    svc = ChallengeService(db_session)
    challenge = svc.offer(_u(user), "t2_reference_check", "Streaming", START)

    references = [{"url": "https://example.com/pricing", "content": "tiers"}]
    verdict = {"met": True, "evidence_ref": "https://elsewhere.com/made-up",
               "text": "Trust me."}
    xp_before = player_xp(db_session)["xp"]
    assert svc.resolve_t2(_u(user), challenge, verdict, references) == "void"
    assert player_xp(db_session)["xp"] == xp_before


# ── 9: T2 adversarial — text says passed, structure says no ────────────────


def test_t2_flavor_text_never_overrides_structured_field(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Streaming")
    _category_history(db_session, acct, "Streaming")
    svc = ChallengeService(db_session)
    challenge = svc.offer(_u(user), "t2_reference_check", "Streaming", START)

    references = [{"url": "https://example.com/pricing", "content": "tiers"}]
    verdict = {"met": False, "evidence_ref": "https://example.com/pricing",
               "text": "Passed! Incredible work — challenge complete!"}
    xp_before = player_xp(db_session)["xp"]
    status = svc.resolve_t2(_u(user), challenge, verdict, references)
    assert status == "soft_landed"  # Law 2: text is flavor, the field decides
    assert player_xp(db_session)["xp"] == xp_before


# ── 10: T3 — cosmetic credit, zero XP, zero verification calls ──────────────


def test_t3_self_report_cosmetic_only_no_verification(db_session, user_acct, monkeypatch):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    svc = ChallengeService(db_session)
    challenge = svc.offer(_u(user), "t3_self_report", "", START)

    calls = {"fetch": 0, "verdict": 0}
    from server.src.services.game import challenge_verdict

    monkeypatch.setattr(challenge_verdict, "fetch_reference",
                        lambda *a, **k: calls.__setitem__("fetch", calls["fetch"] + 1))
    monkeypatch.setattr(challenge_verdict, "structured_verdict",
                        lambda *a, **k: calls.__setitem__("verdict", calls["verdict"] + 1))

    xp_before = player_xp(db_session)["xp"]
    assert svc.complete_t3(_u(user), challenge) == "met"
    assert challenge.cosmetic_credit == 1
    assert player_xp(db_session)["xp"] == xp_before  # zero XP — registry agrees
    assert TIER_XP[3] == 0
    from server.src.services.game.xp import xp_for_event

    assert xp_for_event("ChallengeMet", {"tier": 3}) == 0
    assert calls == {"fetch": 0, "verdict": 0}  # no verification theater


# ── 11: failure/abandon → soft landing, never below baseline ───────────────


def test_soft_land_event_diff_is_only_the_status_marker(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    svc = ChallengeService(db_session)
    challenge = _offer_t1(db_session, user)

    from server.src.services.game.daily import streak_view

    xp_before = player_xp(db_session)["xp"]
    streak_before = streak_view(db_session)
    rows_before = db_session.execute(
        text("SELECT id, type FROM game_events ORDER BY id")).all()

    svc.soft_land_challenge(_u(user), challenge)

    rows_after = db_session.execute(
        text("SELECT id, type FROM game_events ORDER BY id")).all()
    new_rows = rows_after[len(rows_before):]
    assert [r.type for r in new_rows] == ["ChallengeSoftLanded"]  # ONLY the marker
    # User state ≥ baseline in every respect: XP, streak, wards untouched.
    assert player_xp(db_session)["xp"] == xp_before
    assert streak_view(db_session) == streak_before
    assert challenge.status == "soft_landed"
    # No "list of losses" exists: nothing negative is recorded anywhere.
    payload = json.loads(new_rows[0].type and db_session.execute(
        text("SELECT payload FROM game_events ORDER BY id DESC LIMIT 1")
    ).scalar_one())
    assert "penalty" not in payload and "loss" not in payload


# ── 12: success → graduation offer → accept/decline ─────────────────────────


def test_graduation_accept_creates_standing_rule(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    svc = ChallengeService(db_session)
    challenge = _offer_t1(db_session, user)
    assert svc.judge_t1(_u(user), challenge) == "met"

    offer = svc.graduation_offer(challenge)
    assert offer["kind"] == "standing_rule"
    rule = svc.accept_graduation(_u(user), challenge)  # the user-confirmed step
    row = db_session.execute(
        select(RuleORM).where(RuleORM.id == rule.id)).scalar_one()
    assert row.user_id == user.id and row.enabled == 1  # 03's chain: it exists


def test_graduation_decline_suppresses_thirty_days(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    svc = ChallengeService(db_session)
    challenge = _offer_t1(db_session, user)
    svc.judge_t1(_u(user), challenge)

    svc.decline_graduation(_u(user), challenge, AS_OF)
    # Within the 30-day window the same kind is suppressed…
    with pytest.raises(ChallengeError) as err:
        svc.offer(_u(user), "t1_category_free_week", "Delivery",
                  AS_OF + timedelta(days=10), params={"categories": ["Delivery"]})
    assert err.value.reason == "suppressed"
    # …and afterwards it offers again.
    later = svc.offer(_u(user), "t1_category_free_week", "Delivery",
                      AS_OF + timedelta(days=31), params={"categories": ["Delivery"]})
    assert later.status == "active"


# ── Law 1: the challenge lifecycle never touches financial truth ────────────


def test_fingerprint_unchanged_across_challenge_lifecycle(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Delivery")
    _category_history(db_session, acct, "Delivery")
    before = finance_tables_fingerprint(db_session)
    svc = ChallengeService(db_session)
    challenge = _offer_t1(db_session, user)
    svc.judge_t1(_u(user), challenge)  # met → XP event; rules untouched
    after = finance_tables_fingerprint(db_session)
    assert before == after  # (accept_graduation is the user's act, not ours)
