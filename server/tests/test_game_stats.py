"""v4 package 04 — stat engine + XP hygiene tests.

The registry-walk test (group 1) is the law's enforcement: every registered
event type must be explicitly XP-bearing or XP-forbidden. Baselines, the four
stats (with the anti-wealth-ranking property), the level curve, and integrity /
rebuild round out the package.
"""

from __future__ import annotations

import random
from datetime import date

import pytest
from sqlalchemy import text

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.baselines import category_baseline
from server.src.services.game.events import (
    EVENT_TYPES,
    GameEventDraft,
    record_events,
)
from server.src.services.game.rebuild import rebuild_projection
from server.src.services.game.stats import StatsService, player_xp, vitality_bucket
from server.src.services.game.xp import (
    CONSISTENCY_DAILY_CAP,
    XP_FORBIDDEN,
    is_classified,
    level_for_xp,
    xp_for_event,
)
from server.tests.integrity import finance_tables_fingerprint

AS_OF = date(2026, 6, 1)


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="stat", full_name="Stat U", email="stat@x.com",
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


def _spend(db_session, acct, *, category, cents, when):
    db_session.add(ExpenseORM(title=category, amount=cents, date=when,
                              category=category, account_id=acct.id))
    db_session.flush()


# ── 1: registry walk — the law's enforcement ─────────────────────────────


def test_every_registered_event_type_is_classified():
    # Import every module that registers event types so the walk sees the full
    # set (alerts registers AlertFired/AlertFixApplied/WhatIfCommitted; xp/stats
    # register the XP-bearing + engagement types).
    import server.src.services.game.alerts  # noqa: F401
    import server.src.services.game.stats  # noqa: F401

    unclassified = [t for t in EVENT_TYPES if not is_classified(t)]
    assert unclassified == [], (
        f"unclassified event types (add to XP_BEARING or XP_FORBIDDEN): "
        f"{unclassified}"
    )


def test_engagement_shaped_types_are_forbidden():
    # Every engagement-shaped type must be explicitly forbidden.
    for t in ("ModeChanged", "SheetViewed", "LoggedIn", "Collected",
              "AlertDelivered", "AlertFired"):
        assert t in XP_FORBIDDEN, f"{t} must be XP_FORBIDDEN"


# ── 2-3: consistency cap + conditional XP ────────────────────────────────


def test_consistency_xp_is_capped_per_day(db_session):
    folds_mod.register_builtin_folds()
    # 10 consistency verbs in one day → total XP equals the daily cap, not 10×.
    for i in range(10):
        record_events(db_session, [GameEventDraft(
            stream="player", type="ConsistencyVerb",
            payload={"day": "2026-06-01"},
            idempotency_key=f"verb:2026-06-01:{i}",
        )])
    db_session.flush()
    assert player_xp(db_session)["xp"] == CONSISTENCY_DAILY_CAP


def test_checklist_fix_awards_zero_allocation_awards_positive():
    assert xp_for_event("AlertFixApplied", {"fix_kind": "checklist"}) == 0
    assert xp_for_event("AlertFixApplied", {"fix_kind": "create_allocation"}) > 0


# ── regression: stat folds register under the real (events-first) import ──
#
# The XP folds live in stats.py and are wired up by folds.register_builtin_folds.
# stats imports xp imports events, so when folds is first imported *as part of*
# events.py's own import, that chain is circular and the stats import fails. The
# bug: that failure was swallowed AND the sync-folds-present guard then blocked
# any retry, so in the real app order NO XP ever folded into player_state — yet
# every in-process test imported stats directly first, masking it. This test
# reproduces the cold order in a clean subprocess and asserts XP actually moves.


def test_stat_folds_register_under_cold_events_first_import():
    import subprocess
    import sys
    import textwrap

    repo_root = __import__("pathlib").Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import sys
        from sqlalchemy import create_engine, event
        from sqlalchemy.pool import StaticPool
        from sqlalchemy.orm import sessionmaker

        # The real cold order: import ONLY events first (as the app does via
        # main -> routers -> services). Do NOT import stats/xp directly.
        from server.src.db.models import Base
        from server.src.services.game.events import GameEventDraft, record_events

        engine = create_engine("sqlite://",
            connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        s = sessionmaker(bind=engine)()

        record_events(s, [GameEventDraft(stream="player", type="AllocationMade",
                                         payload={}, idempotency_key="cold1")])
        s.flush()

        # Read player_state XP straight from the projection KV (no stats import
        # that would itself fix the registration we're testing).
        from server.src.services.game.folds import kv_get
        state = kv_get(s, "player_state", "xp") or {"xp": 0}
        print("XP", state.get("xp", 0))
        sys.exit(0 if state.get("xp", 0) > 0 else 1)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "AllocationMade recorded under the cold events-first import order did "
        "not fold any XP into player_state — the stats folds failed to register.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "XP" in result.stdout and "XP 0" not in result.stdout


# ── 4: XP clamp end-to-end ───────────────────────────────────────────────


def test_xp_award_then_reversal_does_not_decrease_xp(db_session):
    folds_mod.register_builtin_folds()
    record_events(db_session, [GameEventDraft(
        stream="player", type="AllocationMade", payload={}, idempotency_key="a1")])
    db_session.flush()
    before = player_xp(db_session)["xp"]
    assert before > 0
    # A negative XP correction routed through XpAwarded with a clamped payload.
    from server.src.services.game.clamp import clamped_xp_delta

    applied, true = clamped_xp_delta(-before)
    [ev] = record_events(db_session, [GameEventDraft(
        stream="player", type="XpAwarded",
        payload={"applied": applied, "true": true})])
    db_session.flush()
    import json

    stored = json.loads(ev.payload)
    assert stored["applied"] == 0 and stored["true"] == -before
    # XpAwarded is XP_FORBIDDEN, so it never moves player_state XP anyway.
    assert player_xp(db_session)["xp"] == before


# ── 5-8: baselines ───────────────────────────────────────────────────────


def test_three_month_baseline_math(db_session, user_acct):
    user, acct = user_acct
    # $300 of dining across the 3 prior calendar months (Mar, Apr, May).
    _spend(db_session, acct, category="Dining", cents=100_00, when="2026-03-15")
    _spend(db_session, acct, category="Dining", cents=100_00, when="2026-04-15")
    _spend(db_session, acct, category="Dining", cents=100_00, when="2026-05-15")
    b = category_baseline(db_session, user.id, "Dining", AS_OF)
    assert b.monthly_cents == 100_00  # $300 / 3 months


def test_transfers_excluded_and_refund_nets_out(db_session, user_acct):
    user, acct = user_acct
    # An own-account transfer category is never counted.
    _spend(db_session, acct, category="Transfer", cents=500_00, when="2026-04-10")
    # A dining charge and an equal same-category refund net to zero.
    _spend(db_session, acct, category="Dining", cents=60_00, when="2026-04-10")
    db_session.add(IncomeORM(title="refund", amount=60_00, date="2026-04-11",
                             category="Dining", account_id=acct.id))
    db_session.flush()
    assert category_baseline(db_session, user.id, "Transfer", AS_OF).monthly_cents == 0
    assert category_baseline(db_session, user.id, "Dining", AS_OF).monthly_cents == 0


def test_new_user_is_low_confidence(db_session, user_acct):
    user, acct = user_acct
    # Only a few days of data → low confidence.
    _spend(db_session, acct, category="Dining", cents=10_00, when="2026-05-30")
    b = category_baseline(db_session, user.id, "Dining", AS_OF)
    assert b.low_confidence is True


# ── 9-11: stats ──────────────────────────────────────────────────────────


def test_armor_ignores_essential_category_overruns(db_session, user_acct):
    user, acct = user_acct
    # Flag Rent essential (the migration seeds these, but the test DB is built
    # via create_all which doesn't run the seed — so insert it here).
    from server.src.db.models import CategorySettings as CSORM

    db_session.add(CSORM(name="Rent", essential=1, user_confirmed=0))
    db_session.flush()
    # Seed a discretionary baseline (Dining over the 3 prior months).
    for m in ("03", "04", "05"):
        _spend(db_session, acct, category="Dining", cents=100_00, when=f"2026-{m}-15")
    svc = StatsService(db_session)
    base_armor = svc.armor(user.id, AS_OF)
    # Doubling an ESSENTIAL (Rent, seeded essential) must not lower Armor.
    _spend(db_session, acct, category="Rent", cents=2000_00, when="2026-05-20")
    assert svc.armor(user.id, AS_OF) == base_armor
    # Doubling DISCRETIONARY (Dining) this month DOES lower Armor.
    _spend(db_session, acct, category="Dining", cents=2000_00, when="2026-05-25")
    assert svc.armor(user.id, AS_OF) < base_armor


def test_mana_is_ratio_based_anti_wealth_ranking(db_session):
    # Low-income improver vs high-income flat earner: the ratio rewards
    # improvement, not absolute wealth. We assert Mana is a ratio not tied to
    # absolute income by comparing two users with the same SAVINGS RATE but very
    # different incomes → identical Mana.
    def _seed(uname, income_cents, spend_cents):
        u = UserORM(username=uname, full_name="U", email=f"{uname}@x.com",
                    hashed_password="x", savings_percent=0)
        db_session.add(u)
        db_session.flush()
        a = AccountORM(name="C", type="checking", balance=0, user_id=u.id)
        db_session.add(a)
        db_session.flush()
        for m in ("03", "04", "05"):
            db_session.add(IncomeORM(title="pay", amount=income_cents, date=f"2026-{m}-01",
                                     category="Work", account_id=a.id))
            db_session.add(ExpenseORM(title="life", amount=spend_cents, date=f"2026-{m}-10",
                                      category="Dining", account_id=a.id))
        db_session.flush()
        return u

    poor = _seed("poor", 100_00, 50_00)   # 50% savings rate on $100/mo
    rich = _seed("rich", 1000_00, 500_00)  # 50% savings rate on $1000/mo
    svc = StatsService(db_session)
    assert svc.mana(poor.id, AS_OF) == svc.mana(rich.id, AS_OF)


def test_vitality_buckets_at_boundaries():
    assert vitality_bucket(0.9) == "<1 month"
    assert vitality_bucket(1.1) == "1–2 months"
    assert vitality_bucket(5.0) == "4–6 months"
    assert vitality_bucket(10.0) == "6+ months"


# ── 12: level curve ──────────────────────────────────────────────────────


def test_level_curve_is_monotonic_and_sublinear():
    levels = [level_for_xp(x) for x in range(0, 5000, 50)]
    # Monotonic non-decreasing.
    assert all(b >= a for a, b in zip(levels, levels[1:]))
    # Sub-linear sanity: level(4K) - level(K) < 3 * level(K) for a mid K.
    from server.src.services.game.xp import LEVEL_K

    k = LEVEL_K * 9  # ensures level(K) >= 3 so the property is meaningful
    assert level_for_xp(4 * k) - level_for_xp(k) < 3 * level_for_xp(k)


# ── 16: viewing the sheet emits zero events (engagement probe) ───────────
# (Server has no "view" endpoint that writes events — this is asserted on the
# client side; here we assert the stat read path writes nothing.)


def test_reading_stats_writes_no_events(db_session, user_acct):
    user, acct = user_acct
    before = db_session.execute(text("SELECT COUNT(*) FROM game_events")).scalar_one()
    for _ in range(50):
        StatsService(db_session).compute(_u(user), AS_OF)
    db_session.flush()
    after = db_session.execute(text("SELECT COUNT(*) FROM game_events")).scalar_one()
    assert after == before


# ── 17: integrity + rebuild ──────────────────────────────────────────────


def test_fingerprint_unchanged_by_stat_folds(db_session, user_acct):
    user, acct = user_acct
    before = finance_tables_fingerprint(db_session)
    for i in range(20):
        record_events(db_session, [GameEventDraft(
            stream="player", type="AllocationMade", payload={}, idempotency_key=f"al{i}")])
    db_session.flush()
    assert finance_tables_fingerprint(db_session) == before


def test_rebuild_player_state_reproduces_live(db_session):
    folds_mod.register_builtin_folds()
    rng = random.Random(7)
    types = ["AllocationMade", "RuleExecuted", "BillPaidOnTime", "WhatIfCommitted"]
    for i in range(200):
        t = rng.choice(types)
        record_events(db_session, [GameEventDraft(
            stream="player", type=t, payload={}, idempotency_key=f"e{i}")])
    db_session.flush()
    live = player_xp(db_session)
    rebuild_projection(db_session, "player_state")
    db_session.flush()
    assert player_xp(db_session) == live


def test_mana_reflects_real_current_vs_baseline_not_always_one(db_session):
    """Regression: Mana used to be hard-wired to 1.0 because the 'current' rate
    reused the baseline it divided by. A current month that saves MORE than the
    trailing baseline must score Mana > 1.0."""
    from server.src.db.models import Income as IncomeORM2

    u = UserORM(username="manaimp", full_name="U", email="manaimp@x.com",
                hashed_password="x", savings_percent=0)
    db_session.add(u); db_session.flush()
    a = AccountORM(name="C", type="checking", balance=0, user_id=u.id)
    db_session.add(a); db_session.flush()
    # Baseline (prior 3 months): 50% savings rate ($100 income, $50 spend).
    for m in ("03", "04", "05"):
        db_session.add(IncomeORM2(title="pay", amount=100_00, date=f"2026-{m}-01",
                                  category="Work", account_id=a.id))
        db_session.add(ExpenseORM(title="life", amount=50_00, date=f"2026-{m}-10",
                                  category="Dining", account_id=a.id))
    # Current month (June): income $100, spend only $10 → 90% savings rate.
    db_session.add(IncomeORM2(title="pay", amount=100_00, date="2026-06-01",
                              category="Work", account_id=a.id))
    db_session.add(ExpenseORM(title="life", amount=10_00, date="2026-06-05",
                              category="Dining", account_id=a.id))
    db_session.flush()
    mana = StatsService(db_session).mana(u.id, AS_OF)
    assert mana > 1.0, f"current month improved on baseline but Mana={mana}"
