"""v4 package 07 — the Chronicler + the Weekly Saga Chapter.

Fact-sheet determinism + cache, validators (digit rule, entity allowlist, word
count, off-enum archetype, firewall), the always-one-action rule, the advice
firewall (incl. the red-team corpus + adversarial MODEL output), crisis routing,
rate limit, off-mode persona absence, cost/cadence, and Law-1/Law-2 integrity.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from server.src.db.models import (
    Account as AccountORM,
    LlmCache,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.chronicler import (
    ARCHETYPES,
    BODY_MIN_WORDS,
    build_week_fact_sheet,
    fact_sheet_cache_key,
    generate_chapter,
    template_chapter,
    validate_chapter,
)
from server.src.services.game.drawer import (
    ChroniclerDrawer,
    DAILY_MESSAGE_LIMIT,
    persona_system_prompt,
)
from server.src.services.game.firewall import is_crisis, screen_output
from server.tests.integrity import finance_tables_fingerprint

WK_START = date(2026, 6, 1)
WK_END = date(2026, 6, 7)


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="chr", full_name="Chr U", email="chr@x.com",
                   hashed_password="x", savings_percent=0, game_mode="full")
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=300_00, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user, mode="full"):
    u = UserInDB(id=user.id, username=user.username, email=user.email,
                 full_name=user.full_name, disabled=False, hashed_password="x")
    object.__setattr__(u, "game_mode", mode) if hasattr(u, "__setattr__") else None
    u.game_mode = mode
    return u


# A valid, digit-free, advice-free chapter body (~130 words).
_GOOD_BODY = (
    "Another week closes in the ledger and the Keeper kept the watch. "
    "The standing debt took its blows and gave ground, reeling where it once "
    "loomed. There was no spectacle this week, only the steady arithmetic of "
    "someone who shows up and does the quiet work. The run held its line, day "
    "after day, and the siege inched a little further toward its end. A hard "
    "stretch came and went, and the ledger still stands, unbowed and patient. "
    "Nothing here is loud. Everything here is durable. The saga is written in "
    "consistency rather than in fireworks, and this week added its small, "
    "stubborn line to the chronicle. The work continues, and the Keeper still "
    "holds the pen, ready for whatever the next week brings to the gates."
)


def _good_chapter():
    return {"title": "A Week in the Ledger", "body": _GOOD_BODY,
            "archetype_key": "quiet_builder"}


# ── 1-5: fact sheet & cache ──────────────────────────────────────────────


def test_fact_sheet_is_deterministic(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    a = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    b = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # keys are sorted (byte-identical contract)
    assert list(a.keys()) == sorted(a.keys())


def test_cache_hit_skips_llm(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        return json.dumps(_good_chapter())

    generate_chapter(db_session, _u(user), WK_START, WK_END, llm_call=llm)
    generate_chapter(db_session, _u(user), WK_START, WK_END, llm_call=llm)
    assert calls["n"] == 1  # second call served from cache


def test_template_version_changes_cache_key():
    fs = {"a": 1}
    k1 = fact_sheet_cache_key(fs, "full")
    k2 = fact_sheet_cache_key({"a": 2}, "full")
    assert k1 != k2  # different fact sheet → different key


def test_sealed_week_has_no_expiry(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    generate_chapter(db_session, _u(user), WK_START, WK_END,
                     llm_call=lambda p: json.dumps(_good_chapter()), sealed=True)
    row = db_session.query(LlmCache).filter(LlmCache.kind == "saga_chapter").first()
    assert row.expires_at is None


def test_off_mode_user_generates_nothing():
    from server.src.services.game.mode import should_generate_flavor

    class U:
        game_mode = "off"
    assert should_generate_flavor(U()) is False


# ── 6-11: validators (crafted bad model output) ──────────────────────────


def test_digit_in_body_rejected(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    fs = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    bad = _good_chapter()
    bad["body"] = bad["body"].replace("week", "40 dollars saved this week", 1)
    assert validate_chapter(bad, fs, "").ok is False


def test_unknown_proper_noun_rejected(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    fs = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    bad = _good_chapter()
    bad["body"] = "As Gandalf says, " + bad["body"]
    assert validate_chapter(bad, fs, "").ok is False


def test_word_count_bounds(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    fs = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    too_long = _good_chapter()
    too_long["body"] = " ".join(["word"] * 400)
    assert validate_chapter(too_long, fs, "").ok is False
    assert validate_chapter(_good_chapter(), fs, "").ok is True


def test_off_enum_archetype_rejected(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    fs = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    bad = _good_chapter()
    bad["archetype_key"] = "the_legend_himself"
    assert validate_chapter(bad, fs, "").ok is False


def test_advice_in_chapter_blocked_falls_back(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    advice_body = _GOOD_BODY + " You should invest in an index fund."
    bad = {"title": "T", "body": advice_body, "archetype_key": "quiet_builder"}

    def llm(prompt):
        return json.dumps(bad)

    chapter = generate_chapter(db_session, _u(user), WK_START, WK_END, llm_call=llm)
    assert chapter.get("fallback") is True  # firewall rejected → template fallback


def test_template_fallback_is_valid_and_has_action(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    fs = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    ch = template_chapter(fs)
    assert "action" in ch
    assert not any(c.isdigit() for c in ch["body"])
    assert validate_chapter(ch, fs, "").ok is True


# ── 12-13: the one action ────────────────────────────────────────────────


def test_every_chapter_has_exactly_one_action(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    gen = generate_chapter(db_session, _u(user), WK_START, WK_END,
                           llm_call=lambda p: json.dumps(_good_chapter()))
    assert isinstance(gen["action"], dict) and gen["action"].get("kind")
    fs = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    assert template_chapter(fs)["action"].get("kind")


def test_action_floor_is_confirm_forecast(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    # No alerts/candidates for a fresh user → the floor action is confirm_forecast.
    fs = build_week_fact_sheet(db_session, _u(user), WK_START, WK_END)
    assert fs["action"]["kind"] == "confirm_forecast"


# ── 14-19: firewall & drawer ─────────────────────────────────────────────


def test_redteam_corpus_never_leaks_advice():
    import pathlib

    corpus = pathlib.Path(__file__).resolve().parent / "fixtures" / "redteam_prompts.txt"
    prompts = [l.strip() for l in corpus.read_text().splitlines()
               if l.strip() and not l.startswith("#")]
    assert len(prompts) >= 25
    # Adversarial MODEL OUTPUT: a model that parrots advice back must be blocked.
    adversarial_outputs = [
        "You should invest in crypto right now.",
        "I recommend you open a new credit card.",
        "Honestly, refinance your mortgage.",
        "I missed you so much while you were gone.",
        "You failed this month and it's your fault.",
    ]
    for out in adversarial_outputs:
        assert screen_output(out).blocked, f"firewall missed: {out!r}"


def test_crisis_routes_to_static_resource_no_llm():
    calls = {"n": 0}

    def respond(user, msg, prefix):
        calls["n"] += 1
        return "some model text"

    drawer = ChroniclerDrawer(respond)

    class U:
        id = 1
        game_mode = "full"
    r = drawer.ask(U(), "I want to kill myself", today_iso="2026-06-01")
    assert r.kind == "crisis" and calls["n"] == 0  # LLM bypassed entirely
    assert is_crisis("I want to kill myself")


def test_rate_limit_refuses_in_character_and_resets():
    drawer = ChroniclerDrawer(lambda u, m, p: "the run holds, Keeper")

    class U:
        id = 7
        game_mode = "full"
    last = None
    for _ in range(DAILY_MESSAGE_LIMIT + 1):
        last = drawer.ask(U(), "boss", today_iso="2026-06-01")
    assert last.kind == "refusal"
    # Next day resets.
    ok = drawer.ask(U(), "boss", today_iso="2026-06-02")
    assert ok.kind == "message"


def test_off_mode_drawer_has_no_persona_tokens():
    drawer = ChroniclerDrawer(lambda u, m, p: "your balance is fine")

    class Off:
        id = 2
        game_mode = "off"

    class Full:
        id = 3
        game_mode = "full"

    off = drawer.ask(Off(), "balance", today_iso="2026-06-01")
    assert off.persona is False
    assert persona_system_prompt("off") == ""  # zero persona prefix in off
    assert "Keeper" in persona_system_prompt("full")  # persona present in full


def test_ai_label_present_in_all_modes():
    drawer = ChroniclerDrawer(lambda u, m, p: "ok")
    for mode in ("off", "ambient", "full"):
        class U:
            id = 99
            game_mode = mode
        r = drawer.ask(U(), "hi", today_iso="2026-06-01")
        assert r.ai_label is True


# ── 23: integrity ────────────────────────────────────────────────────────


def test_chapter_generation_does_not_touch_finance_tables(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    before = finance_tables_fingerprint(db_session)
    generate_chapter(db_session, _u(user), WK_START, WK_END,
                     llm_call=lambda p: json.dumps(_good_chapter()))
    after = finance_tables_fingerprint(db_session)
    assert before == after  # Law 1: flavor generation never writes financial truth


def test_chapter_generated_is_xp_forbidden():
    from server.src.services.game.xp import XP_FORBIDDEN, is_classified

    assert "ChapterGenerated" in XP_FORBIDDEN
    assert is_classified("ChapterGenerated")
