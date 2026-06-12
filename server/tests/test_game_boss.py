"""v4 package 06 — debt boss battles.

Damage/HP from real payments, crit boundary, corrections/reversals (truth, no
celebration), heal = real APR, empower (no fictional HP), 20% phases, defeat-by-
date + the Grace 'retreat' copy switch, snowball/avalanche ordering math, the
one-active concentration rule, closure (seal/banish, permanent), habit-monsters,
the agency-language lint, the juice allowlist, and integrity + rebuild.
"""

from __future__ import annotations

from datetime import date

import pytest

from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.boss import (
    BossService,
    DebtSpec,
    JUICE_EVENTS,
    boss_view,
    is_juice_event,
    monthly_apr_interest_cents,
    ordering_interest_delta,
)
from server.src.services.game.liability_service import (
    LiabilityService,
    LiabilityError,
)
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.game.rebuild import rebuild_projection
from server.tests.integrity import finance_tables_fingerprint

AS_OF = date(2026, 6, 1)


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="boss", full_name="Boss U", email="boss@x.com",
                   hashed_password="x", savings_percent=0)
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=500_00, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


def _liab(db_session, user, **kw):
    defaults = dict(name="Card", kind="credit_card", principal_cents=500000,
                    apr_bps=2400, minimum_payment_cents=10000)
    defaults.update(kw)
    return LiabilityService(db_session).create(_u(user), **defaults)


# ── 1-5: damage & HP ─────────────────────────────────────────────────────


def test_payment_damages_once_idempotent(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user)
    svc = BossService(db_session)
    svc.register_payment(liab.id, 50000, txn_id="t1")
    svc.register_payment(liab.id, 50000, txn_id="t1")  # replay same txn
    assert boss_view(db_session, liab.id)["hp"] == 450000


def test_crit_threshold_boundary(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, minimum_payment_cents=10000)
    svc = BossService(db_session)
    # min*1.25 = 12500. below, at, above.
    assert is_juice_event("BossDamaged", {"crit": 12400 > 12500}) is False
    # crit flag is computed in register_payment; assert via emitted event payload
    svc.register_payment(liab.id, 12500, txn_id="at")     # == boundary, not >
    svc.register_payment(liab.id, 12600, txn_id="above")  # > boundary → crit
    import json
    from server.src.db.models import GameEvent
    evs = [json.loads(e.payload) for e in db_session.query(GameEvent)
           .filter(GameEvent.type == "BossDamaged").all()]
    crits = {e["amount"]: e["crit"] for e in evs}
    assert crits[12500] is False and crits[12600] is True


def test_correction_raises_hp_no_negative_celebration(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user)
    svc = BossService(db_session)
    svc.register_payment(liab.id, 100000, txn_id="t1")
    assert boss_view(db_session, liab.id)["hp"] == 400000
    # a correction that reduces the counted payment by 40000 → HP rises
    record_events(db_session, [GameEventDraft(
        stream=f"boss:{liab.id}", type="BossCorrected",
        payload={"liability_id": liab.id, "hp_delta": 40000},
        idempotency_key="corr1")])
    db_session.flush()
    assert boss_view(db_session, liab.id)["hp"] == 440000
    # the juice allowlist has no negative/correction event
    assert "BossCorrected" not in JUICE_EVENTS
    assert not is_juice_event("BossCorrected", {})


def test_overpay_clamps_zero_and_defeats_once(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=100000)
    svc = BossService(db_session)
    v = svc.register_payment(liab.id, 150000, txn_id="big")  # overpay
    assert v["hp"] == 0 and v["defeated"] is True
    from server.src.db.models import GameEvent
    defeats = db_session.query(GameEvent).filter(
        GameEvent.type == "BossDefeated").count()
    assert defeats == 1


# ── 6-7: heal & empower ──────────────────────────────────────────────────


def test_monthly_heal_equals_real_apr(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    # 24% APR on $1,000 → monthly = 1000 * 0.24/12 = $20 = 2000 cents.
    assert monthly_apr_interest_cents(100000, 2400) == 2000
    liab = _liab(db_session, user, principal_cents=100000, apr_bps=2400)
    svc = BossService(db_session)
    interest = svc.accrue_monthly_interest(liab.id, "2026-06")
    assert interest == 2000
    assert boss_view(db_session, liab.id)["hp"] == 102000  # heal raised HP


def test_empower_adds_no_hp(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=100000)
    svc = BossService(db_session)
    svc.register_payment(liab.id, 10000, txn_id="t1")
    hp = boss_view(db_session, liab.id)["hp"]
    svc.empower(liab.id, "2026-06")
    assert boss_view(db_session, liab.id)["hp"] == hp  # unchanged


# ── 8-9: phases & defeat-by-date ─────────────────────────────────────────


def test_phases_break_once_each_across_replays(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=500000)
    svc = BossService(db_session)
    # pay down in chunks crossing 4000/3000/2000/1000/0 (cents *100)
    for i, amt in enumerate([100000, 100000, 100000, 100000, 100000]):
        svc.register_payment(liab.id, amt, txn_id=f"p{i}")
    from server.src.db.models import GameEvent
    import json
    phases = sorted(json.loads(e.payload)["phase"] for e in db_session.query(GameEvent)
                    .filter(GameEvent.type == "BossPhaseBroken").all())
    assert phases == [1, 2, 3, 4, 5]
    # rebuild and confirm phase indices are stable (idempotent per index)
    rebuild_projection(db_session, "boss_state")
    assert boss_view(db_session, liab.id)["phases_broken"] == [1, 2, 3, 4, 5]


def test_defeat_by_date_moves_in_on_damage_and_retreats_under_grace(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=100000, minimum_payment_cents=10000)
    svc = BossService(db_session)
    eta0 = svc.defeat_by_date(_u(user), liab.id, AS_OF)
    svc.register_payment(liab.id, 50000, txn_id="t1")  # big extra payment
    eta1 = svc.defeat_by_date(_u(user), liab.id, AS_OF)
    assert eta1["date"] <= eta0["date"]  # date pulled in (or equal)
    # Under Grace the copy KEY switches to the retreat variant (assert the key).
    grace = svc.defeat_by_date(_u(user), liab.id, AS_OF, grace=True)
    assert grace["copy_key"] == "boss.retreat"
    assert eta1["copy_key"] == "boss.defeat_eta"


# ── 10-11: selection & ordering ──────────────────────────────────────────


def test_ordering_interest_delta_golden(db_session, user_acct):
    # $1,000 @ 6% vs $3,000 @ 29% with $300/mo extra: avalanche clearly cheaper.
    debts = [DebtSpec(100000, 600, 5000), DebtSpec(300000, 2900, 6000)]
    d = ordering_interest_delta(debts, 30000)
    assert d["avalanche_interest_cents"] < d["snowball_interest_cents"]
    assert d["delta_cents"] > 0  # positive → avalanche saves this many cents


def test_one_active_boss_enforced(db_session, user_acct):
    user, _ = user_acct
    svc = LiabilityService(db_session)
    a = _liab(db_session, user, name="A", principal_cents=100000)
    b = _liab(db_session, user, name="B", principal_cents=300000)
    svc.set_active_boss(_u(user), a.id)
    with pytest.raises(LiabilityError):
        svc.set_active_boss(_u(user), b.id)


def test_default_order_smallest_first(db_session, user_acct):
    user, _ = user_acct
    _liab(db_session, user, name="Big", principal_cents=300000)
    _liab(db_session, user, name="Small", principal_cents=50000)
    order = LiabilityService(db_session).default_boss_order(_u(user))
    assert order[0].name == "Small"


# ── 12-13: closure ───────────────────────────────────────────────────────


def test_seal_and_banish_record_status(db_session, user_acct):
    user, _ = user_acct
    svc = LiabilityService(db_session)
    a = _liab(db_session, user, name="A")
    b = _liab(db_session, user, name="B")
    sealed = svc.close(_u(user), a.id, sealed=True)
    banished = svc.close(_u(user), b.id, sealed=False)
    assert sealed.status == "defeated_sealed"
    assert banished.status == "defeated_banished"


def test_defeat_is_permanent(db_session, user_acct):
    user, _ = user_acct
    svc = LiabilityService(db_session)
    a = _liab(db_session, user)
    svc.close(_u(user), a.id, sealed=True)
    with pytest.raises(LiabilityError):
        svc.close(_u(user), a.id, sealed=False)  # cannot re-close / resurrect


# ── 14: agency-language lint ─────────────────────────────────────────────

import json as _json
from pathlib import Path as _Path

_TERMS_DIR = _Path(__file__).resolve().parents[2] / "client" / "src" / "terms"
_BANNED_AGENCY = (
    "you failed", "you lost", "you fed", "you fell", "your fault",
    "missed payment",
)


def test_agency_language_lint_over_boss_templates():
    for mode in ("off", "ambient", "full"):
        terms = _json.loads((_TERMS_DIR / f"terms.{mode}.json").read_text())
        for key, value in terms.items():
            if not (key.startswith("boss") or key.startswith("monster")):
                continue
            low = value.lower()
            for phrase in _BANNED_AGENCY:
                assert phrase not in low, f"agency phrase {phrase!r} in {mode}:{key}"


# ── 15-17: habit-monsters ────────────────────────────────────────────────


def _budget(db_session, user, category, monthly_cents):
    db_session.add(BudgetORM(user_id=user.id, category=category,
                             monthly_limit=monthly_cents, rollover=0))
    db_session.flush()


def test_monster_spawn_matrix(db_session, user_acct):
    user, acct = user_acct
    # essential category (rent) flagged; discretionary (dining) not.
    db_session.add(CategorySettingsORM(name="Rent", essential=1))
    db_session.add(CategorySettingsORM(name="Dining", essential=0))
    db_session.flush()
    _budget(db_session, user, "Dining", 100_00)
    _budget(db_session, user, "Rent", 100_00)
    # spend dining 200% (way over pace), rent 200% (essential → never spawns)
    for cat in ("Dining", "Rent"):
        db_session.add(ExpenseORM(title=cat, amount=200_00, date=AS_OF.isoformat(),
                                  category=cat, account_id=acct.id))
    db_session.flush()
    from server.src.services.game.habit_monsters import detect_monsters
    monsters = detect_monsters(db_session, _u(user), AS_OF)
    keys = {m["key"] for m in monsters}
    assert "Dining" in keys
    assert "Rent" not in keys  # essentials never spawn


def test_monster_cap_of_two(db_session, user_acct):
    user, acct = user_acct
    for cat in ("A", "B", "C"):
        db_session.add(CategorySettingsORM(name=cat, essential=0))
        _budget(db_session, user, cat, 100_00)
        db_session.add(ExpenseORM(title=cat, amount=300_00, date=AS_OF.isoformat(),
                                  category=cat, account_id=acct.id))
    db_session.flush()
    from server.src.services.game.habit_monsters import detect_monsters
    monsters = detect_monsters(db_session, _u(user), AS_OF)
    assert len(monsters) <= 2


# ── 18: ASCII determinism is tested client-side (boss.test.tsx) ───────────


# ── 19: juice allowlist walk ─────────────────────────────────────────────


def test_juice_allowlist_excludes_purchases_and_plain_damage():
    # A purchase (TxnPosted) must never juice.
    assert not is_juice_event("TxnPosted", {"amount": 9999})
    # Plain (non-crit) damage must never juice; crit does.
    assert not is_juice_event("BossDamaged", {"crit": False})
    assert is_juice_event("BossDamaged", {"crit": True})
    # Plain RuleExecuted doesn't juice; the sweep kind does.
    assert not is_juice_event("RuleExecuted", {"kind": "categorize"})
    assert is_juice_event("RuleExecuted", {"kind": "sweep"})
    # The registry is a subset of payoff events — no engagement event in it.
    for forbidden in ("TxnPosted", "SheetViewed", "ModeChanged", "DayClosed"):
        assert forbidden not in JUICE_EVENTS


# ── 21-22: rule semantics + integrity/rebuild ────────────────────────────


def test_pay_liability_rule_records_intent_only(db_session, user_acct):
    """v1 semantics: the rules engine only auto-funds target_kind='goal'. A
    'liability'-targeted allocation is NOT auto-executed — it returns
    unsupported_target, so a pay_liability rule records intent and the boss takes
    damage when the REAL payment posts (via BossService.register_payment).
    Documented in the handoff."""
    from server.src.db.models import Rule as RuleORM
    from server.src.services.rule_engine import RuleEngine

    user, _ = user_acct
    liab = _liab(db_session, user, principal_cents=100000)
    rule = RuleORM(user_id=user.id, name="round up to card", enabled=1,
                   action_type="allocate", action_params="{}",
                   target_kind="liability", target_id=liab.id)
    db_session.add(rule)
    db_session.flush()
    cents, status = RuleEngine(db_session)._fund_target(rule, 5000)
    assert cents == 0 and status == "unsupported_target:liability"
    # The liability balance is untouched by the rule (damage needs a real payment).
    assert boss_view(db_session, liab.id)["hp"] in (None, 100000)


def test_full_boss_lifecycle_fingerprint_and_rebuild(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=200000, minimum_payment_cents=10000)
    before = finance_tables_fingerprint(db_session)
    svc = BossService(db_session)
    svc.register_payment(liab.id, 50000, txn_id="t1")
    svc.register_payment(liab.id, 50000, txn_id="t2")
    svc.accrue_monthly_interest(liab.id, "2026-06")
    svc.register_payment(liab.id, 200000, txn_id="t3")  # overkill → defeat
    live = boss_view(db_session, liab.id)
    after = finance_tables_fingerprint(db_session)
    # Law 1: a boss lifecycle never touches accounts/expenses/income/budgets/goals.
    # (liabilities IS truth-adjacent but is written only via LiabilityService.)
    assert before == after
    rebuild_projection(db_session, "boss_state")
    rebuilt = boss_view(db_session, liab.id)
    assert rebuilt["hp"] == live["hp"]
    assert rebuilt["defeated"] == live["defeated"]
    assert rebuilt["phases_broken"] == live["phases_broken"]


# ── regression: amortization non-convergence (thin minimum) ──────────────


def test_amortization_reports_non_convergence_for_thin_minimum():
    # $5,000 @ 25% APR with a $50 minimum: monthly interest (~$104) exceeds the
    # payment, so the balance grows forever. The override screen must say "won't
    # be paid off", NOT return a garbage multi-trillion-dollar figure.
    debts = [DebtSpec(500000, 2500, 5000)]
    d = ordering_interest_delta(debts, 0)
    assert d["amortizes"] is False
    assert d["delta_cents"] is None
    assert d["snowball_interest_cents"] is None
    # A healthy debt still amortizes and yields real numbers.
    ok = ordering_interest_delta([DebtSpec(100000, 1200, 20000)], 0)
    assert ok["amortizes"] is True and ok["snowball_interest_cents"] >= 0


# ── regression: correction un-defeats a boss ─────────────────────────────


def test_correction_undefeats_boss_and_restores_healing(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=100000)
    svc = BossService(db_session)
    svc.register_payment(liab.id, 100000, txn_id="t1")  # defeats it
    assert boss_view(db_session, liab.id)["defeated"] is True
    # A reversal/correction restores HP → the boss must NOT stay defeated.
    record_events(db_session, [GameEventDraft(
        stream=f"boss:{liab.id}", type="BossCorrected",
        payload={"liability_id": liab.id, "hp_delta": 100000},
        idempotency_key="corr-undefeat")])
    db_session.flush()
    v = boss_view(db_session, liab.id)
    assert v["hp"] == 100000 and v["defeated"] is False
    # And a subsequent APR heal now actually applies (it was dropped before).
    svc.accrue_monthly_interest(liab.id, "2026-06")
    assert boss_view(db_session, liab.id)["hp"] > 100000


# ── regression: reconcile moves boss HP ──────────────────────────────────


def test_reconcile_emits_boss_correction_and_moves_hp(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=100000)
    svc = BossService(db_session)
    svc.register_payment(liab.id, 40000, txn_id="t1")  # HP → 60000
    assert boss_view(db_session, liab.id)["hp"] == 60000
    # Reconcile to an observed balance of 70000 (drift of +10000 vs principal).
    LiabilityService(db_session).reconcile(_u(user), liab.id, 110000, "drift")
    # principal was 100000; observed 110000 → delta +10000 → HP rises by 10000.
    assert boss_view(db_session, liab.id)["hp"] == 70000


# ── regression: defeat-by-date preserves day-of-month ────────────────────


def test_defeat_by_date_preserves_day_of_month(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    liab = _liab(db_session, user, principal_cents=30000, minimum_payment_cents=10000)
    svc = BossService(db_session)
    from datetime import date as _date
    eta = svc.defeat_by_date(_u(user), liab.id, _date(2026, 6, 17))
    # 30000 / 10000 = 3 months from June 17 → ~Sept 17, NOT snapped to the 1st.
    assert eta["date"].endswith("-17"), eta["date"]


# ── regression: creeper detection fires on a rising price ────────────────


def test_creeper_fires_on_rising_subscription_price(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # A still-billed monthly subscription whose price crept up >15% over time.
    # (months-since-last-charge would never flag this — it's charged monthly.)
    from server.src.db.models import Expense as ExpenseORM
    prices = [(("2026-02-05"), 10_00), (("2026-03-05"), 10_00),
              (("2026-04-05"), 12_00), (("2026-05-05"), 13_00)]
    for when, cents in prices:
        db_session.add(ExpenseORM(title="Streamly", amount=cents, date=when,
                                  category="Streaming", account_id=acct.id))
    db_session.flush()
    from server.src.services.game.habit_monsters import detect_monsters
    monsters = detect_monsters(db_session, _u(user), date(2026, 5, 20))
    creepers = [m for m in monsters if m["kind"] == "creeper"]
    assert any(m["reason"] == "rising_price" for m in creepers), monsters
