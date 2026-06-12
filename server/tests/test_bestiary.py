"""v4 package 09 — bestiary + regret-monster.

Cache stability (same seed → same name forever; salt bump → new name), the
trademark transform (merchant never verbatim in the name), validators (digits/
firewall), regret aspect threshold + quiet drop + zero-XP, and the
punitive-words ban on regret copy.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    LlmCache,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.bestiary import (
    generate_bestiary_entry,
    template_entry,
    validate_entry,
)
from server.src.services.game.depth import (
    REGRET_BANNED_WORDS,
    category_has_regret_aspect,
    regret_lore_line,
)

AS_OF = date(2026, 6, 15)


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="best", full_name="Best U", email="best@x.com",
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


# ── 16: cache stability + salt rename ──────────────────────────────────────


def _good_llm(merchant):
    def call(prompt):
        return json.dumps({
            "name": "The Gilded Wyrm", "epithet": "keeper of unpaid dues",
            "taunt_gentle": "It stirs when the ledger sleeps.",
            "taunt_roast": "It feeds on neglect — starve it.",
            "defeat_line": "It crumbles to dust.",
        })
    return call


def test_same_seed_same_name_across_generations_and_rebuild(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    facts = {"category": "dining", "debt_kind": "credit_card"}
    first = generate_bestiary_entry(db_session, "boss", "seedABC", facts, "Chase",
                                    llm_call=_good_llm("Chase"))
    # 10 more generations → identical (served from cache).
    for _ in range(10):
        again = generate_bestiary_entry(db_session, "boss", "seedABC", facts, "Chase",
                                        llm_call=_good_llm("Chase"))
        assert again["name"] == first["name"]
    # Only ONE cache row for this seed+salt.
    assert db_session.query(LlmCache).filter(
        LlmCache.kind == "bestiary_entry").count() == 1


def test_rename_salt_bumps_to_new_name(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    facts = {"category": "dining", "debt_kind": "credit_card"}
    a = generate_bestiary_entry(db_session, "boss", "seedABC", facts, "Chase",
                                salt=0, llm_call=None)  # template (deterministic)
    b = generate_bestiary_entry(db_session, "boss", "seedABC", facts, "Chase",
                                salt=1, llm_call=None)
    # Different salt → a separate cache entry exists (rename creates a new one).
    assert db_session.query(LlmCache).filter(
        LlmCache.kind == "bestiary_entry").count() == 2
    # Templates are deterministic per merchant, so names match here, but the
    # SALTED KEY differs — a real LLM regen would differ. Assert key separation.
    from server.src.services.game.bestiary import bestiary_cache_key

    assert bestiary_cache_key("boss", "seedABC", 0) != bestiary_cache_key("boss", "seedABC", 1)
    assert a["name"] and b["name"]


# ── 17: trademark transform ────────────────────────────────────────────────


def test_name_never_contains_merchant_verbatim(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    facts = {"category": "streaming", "debt_kind": "credit_card"}
    # A model that tries to leak the trademark must be rejected → template.
    def leaky(prompt):
        return json.dumps({
            "name": "The Netflix Wyrm", "epithet": "binge-keeper",
            "taunt_gentle": "g", "taunt_roast": "r", "defeat_line": "d",
        })
    entry = generate_bestiary_entry(db_session, "boss", "seedN", facts, "Netflix",
                                    llm_call=leaky)
    assert "netflix" not in entry["name"].lower()


def test_validators_reject_digits_and_advice():
    facts = {"category": "dining"}
    ok, _ = validate_entry({
        "name": "The Wyrm", "epithet": "e", "taunt_gentle": "saved 40 dollars",
        "taunt_roast": "r", "defeat_line": "d"}, facts, "Chase")
    assert ok is False  # digit in body
    ok2, _ = validate_entry({
        "name": "The Wyrm", "epithet": "e",
        "taunt_gentle": "you should invest in crypto",
        "taunt_roast": "r", "defeat_line": "d"}, facts, "Chase")
    assert ok2 is False  # firewall


# ── 19: regret aspect ───────────────────────────────────────────────────────


def _regret_txn(db, acct, when):
    db.add(ExpenseORM(title="Takeout", amount=30_00, date=when, category="Dining",
                      worth_it="no", account_id=acct.id))
    db.flush()


def test_regret_aspect_threshold_and_quiet_drop(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # 2 regret tags → off.
    _regret_txn(db_session, acct, "2026-06-01")
    _regret_txn(db_session, acct, "2026-06-05")
    assert category_has_regret_aspect(db_session, _u(user), "Dining", AS_OF) is False
    # 3rd → on.
    _regret_txn(db_session, acct, "2026-06-10")
    assert category_has_regret_aspect(db_session, _u(user), "Dining", AS_OF) is True


def test_regret_aspect_grants_no_xp(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    from server.src.services.game.stats import player_xp

    before = player_xp(db_session)["xp"]
    for d in ("2026-06-01", "2026-06-05", "2026-06-10"):
        _regret_txn(db_session, acct, d)
    category_has_regret_aspect(db_session, _u(user), "Dining", AS_OF)
    assert player_xp(db_session)["xp"] == before  # reading regret never moves XP


def test_regret_copy_is_not_punitive():
    line = regret_lore_line("Dining").lower()
    for w in REGRET_BANNED_WORDS:
        assert w not in line
    assert "marked" in line  # reflective framing
