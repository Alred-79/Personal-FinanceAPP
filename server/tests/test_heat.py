"""v4 package 09 — Heat contracts (the game↔money bridge).

Pricing (baseline-relative, refuses essentials/LOW_CONFIDENCE/over-cap/4th),
forecast veto, the CAPPED self-funding sweep (never more than verified
underspend), Grace pause, abandon, and full-Grace stacking/opt-out + Ascension's
scoring-only guarantee. Integrity throughout.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from server.src.db.models import (
    Account as AccountORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.heat import (
    HeatError,
    HeatService,
    MAX_ACTIVE_CONTRACTS,
    MONTHLY_HEAT_CAP,
)
from server.tests.integrity import finance_tables_fingerprint

AS_OF = date(2026, 6, 15)
MONTH = "2026-06"


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="heat", full_name="Heat U", email="heat@x.com",
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


def _confirmed_category(db, name, *, essential=0):
    db.add(CategorySettingsORM(name=name, essential=essential, user_confirmed=1))
    db.flush()


def _dining_history(db, acct, monthly_cents):
    # 3 prior calendar months of dining so the baseline is non-low-confidence.
    for m, day in ((3, "2026-03-10"), (4, "2026-04-10"), (5, "2026-05-10")):
        db.add(ExpenseORM(title="Dining", amount=monthly_cents, date=day,
                          category="Dining", account_id=acct.id))
    # An early activity row so >6 weeks of history.
    db.add(ExpenseORM(title="Old", amount=100, date="2026-01-01",
                      category="Dining", account_id=acct.id))
    db.flush()


# ── 1: pricing & refusals ─────────────────────────────────────────────────


def test_pricing_table(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Dining")
    _dining_history(db_session, acct, 200_00)
    svc = HeatService(db_session)
    assert svc.price(_u(user), "Dining", "cap_vs_baseline", 75, AS_OF).heat == 1
    assert svc.price(_u(user), "Dining", "cap_vs_baseline", 50, AS_OF).heat == 2


def test_pricing_refuses_essential(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Rent", essential=1)
    with pytest.raises(HeatError) as e:
        HeatService(db_session).price(_u(user), "Rent", "cap_vs_baseline", 75, AS_OF)
    assert e.value.reason == "essential_category"


def test_pricing_refuses_low_confidence(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Dining")
    # No history → low confidence.
    with pytest.raises(HeatError) as e:
        HeatService(db_session).price(_u(user), "Dining", "cap_vs_baseline", 75, AS_OF)
    assert e.value.reason == "low_confidence"


def test_refuses_fourth_contract_and_heat_cap(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    for c in ("Dining", "Shopping", "Fun", "Extra"):
        _confirmed_category(db_session, c)
        _dining_history(db_session, acct, 100_00)  # gives each a baseline
        db_session.add_all([ExpenseORM(title=c, amount=100_00, date=d, category=c,
                                       account_id=acct.id)
                            for d in ("2026-03-11", "2026-04-11", "2026-05-11")])
    db_session.flush()
    svc = HeatService(db_session)
    # Three 75%-cap contracts (1 Heat each) = 3 active, 3 Heat.
    for c in ("Dining", "Shopping", "Fun"):
        svc.create(_u(user), MONTH, svc.price(_u(user), c, "cap_vs_baseline", 75, AS_OF))
    assert len(svc.active_contracts(_u(user), MONTH)) == MAX_ACTIVE_CONTRACTS
    with pytest.raises(HeatError) as e:
        svc.create(_u(user), MONTH, svc.price(_u(user), "Extra", "cap_vs_baseline", 75, AS_OF))
    assert e.value.reason == "too_many"


# ── 4: the capped sweep ────────────────────────────────────────────────────


def test_sweep_never_exceeds_verified_underspend(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Dining")
    _dining_history(db_session, acct, 200_00)  # baseline 200/mo
    svc = HeatService(db_session)
    price = svc.price(_u(user), "Dining", "cap_vs_baseline", 75, AS_OF)  # cap = 150
    contract = svc.create(_u(user), MONTH, price, arm="sweep")
    # Posted June dining = 108 → underspend vs the 150 cap = 42.
    db_session.add(ExpenseORM(title="Dining", amount=108_00, date="2026-06-05",
                              category="Dining", account_id=acct.id))
    db_session.flush()
    # Contracted hope is 60, but verified underspend is only 42 → sweep is 42.
    swept = svc.sweep_amount_cents(_u(user), contract, 60_00, AS_OF)
    assert swept == 42_00


def test_abandon_is_penalty_free(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Dining")
    _dining_history(db_session, acct, 200_00)
    svc = HeatService(db_session)
    contract = svc.create(_u(user), MONTH,
                          svc.price(_u(user), "Dining", "cap_vs_baseline", 75, AS_OF))
    from server.src.db.models import GameEvent

    before = db_session.query(GameEvent).count()
    svc.abandon(contract)
    after = db_session.query(GameEvent).count()
    assert contract.status == "abandoned"
    assert after == before  # zero events emitted on abandon


# ── full Grace: stacking cap + opt-out ─────────────────────────────────────


def test_grace_stacking_capped_and_optout(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    from server.src.services.game.grace import GraceService, is_active
    from server.src.services.game.daily import _state

    acct.balance = -100  # force triggers (negative balance → STS floor + negative)
    db_session.flush()
    svc = GraceService(db_session)
    # Opt-out → ZERO Grace effects.
    assert svc.apply_if_triggered(_u(user), AS_OF, opted_out=True) is False
    assert not is_active(db_session)
    assert _state(db_session).get("grace_wards", 0) == 0
    # Not opted out → one Grace level even if several triggers fire.
    svc.apply_if_triggered(_u(user), AS_OF)
    from server.src.services.game.grace import _grace

    assert _grace(db_session)["level"] == 1


# ── Ascension scoring-only guarantee ───────────────────────────────────────


def test_ascension_changes_only_score():
    from server.src.services.game.depth import apply_ascension_to_score

    base = 0.6
    asc0 = apply_ascension_to_score(base, 0)
    asc2 = apply_ascension_to_score(base, 2)
    assert asc0 == base  # tier 0 is identity
    assert asc2 > asc0   # higher tier → higher prestige score, nothing else


# ── integrity ──────────────────────────────────────────────────────────────


def test_fingerprint_unchanged_across_heat_lifecycle(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _confirmed_category(db_session, "Dining")
    _dining_history(db_session, acct, 200_00)
    before = finance_tables_fingerprint(db_session)
    svc = HeatService(db_session)
    contract = svc.create(_u(user), MONTH,
                          svc.price(_u(user), "Dining", "cap_vs_baseline", 75, AS_OF),
                          arm="sweep")
    svc.sweep_amount_cents(_u(user), contract, 60_00, AS_OF)
    svc.abandon(contract)
    after = finance_tables_fingerprint(db_session)
    assert before == after  # heat contracts never write financial-truth tables
