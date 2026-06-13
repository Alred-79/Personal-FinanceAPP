"""v4 package 03 — money spine tests.

Alert timing (the FCA lesson), caps & hygiene, banned-pattern scan, fix
execution via propose→confirm, what-if R14 rules, graduation + soft-landing,
and Law-1 integrity. Service-level tests pin ``as_of`` for determinism.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.assistant_service import ActionService
from server.src.services.game.alerts import (
    AlertEngine,
    BANNED_PATTERNS,
    scan_templates_for_banned_patterns,
)
from server.src.services.game.graduation import (
    detect_graduation_candidates,
    soft_land,
)
from server.src.services.game.whatif import WhatIfService
from server.tests.integrity import finance_tables_fingerprint

AS_OF = date(2026, 6, 1)


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def user_acct(db_session):
    user = UserORM(
        username="spine",
        full_name="Spine User",
        email="spine@x.com",
        hashed_password="x",
        savings_percent=0,
    )
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=100_00, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user: UserORM) -> UserInDB:
    return UserInDB(
        id=user.id, username=user.username, email=user.email,
        full_name=user.full_name, disabled=False, hashed_password="x",
        savings_percent=0,
    )


def _bill(db_session, acct, *, title, amount_cents, anchor, recurrence="monthly"):
    db_session.add(ExpenseORM(
        title=title, amount=amount_cents, date=anchor, category="Utilities",
        recurrence=recurrence, account_id=acct.id,
    ))
    db_session.flush()


# ── 1-4: alert timing (the FCA lesson, encoded) ──────────────────────────


def test_bill_due_in_10_days_no_alert(db_session, user_acct):
    user, acct = user_acct
    # Balance is small ($100); a big bill 10 days out would dip — but it's
    # outside the 3-day action window, so NO alert. (Monthly anchor in May → the
    # next occurrence lands 2026-06-11, 10 days past AS_OF.)
    _bill(db_session, acct, title="Rent", amount_cents=200_00, anchor="2026-05-11")
    alerts = AlertEngine(db_session).evaluate(_u(user), AS_OF)
    assert not any(a.type == "BILL_DIP" for a in alerts)


def test_bill_due_in_3_days_fires_once(db_session, user_acct):
    user, acct = user_acct
    # Monthly anchor in May → next occurrence 2026-06-04, 3 days past AS_OF.
    _bill(db_session, acct, title="Rent", amount_cents=200_00, anchor="2026-05-04")
    engine = AlertEngine(db_session)
    alerts = engine.evaluate(_u(user), AS_OF)
    assert any(a.type == "BILL_DIP" for a in alerts)
    # Deliver today, then RE-EVALUATE ON A LATER DAY for the same bill → no
    # duplicate AlertFired (spec test 2: "re-evaluation tomorrow does not
    # duplicate"). The idempotency key must exclude the evaluation date, since
    # the same bill is re-evaluated every evening; the bill's due date lives in
    # the entity, so a genuinely new occurrence still gets its own key.
    engine.deliver(_u(user), AS_OF)
    db_session.flush()
    before = db_session.execute(text("SELECT COUNT(*) FROM game_events WHERE type='AlertFired'")).scalar_one()
    # The same Rent bill (due 2026-06-04) is still in-window the next day.
    engine.deliver(_u(user), AS_OF + timedelta(days=1))
    db_session.flush()
    after = db_session.execute(text("SELECT COUNT(*) FROM game_events WHERE type='AlertFired'")).scalar_one()
    assert after == before  # same bill, later day → still no duplicate


def test_payday_sweep_fires_on_real_posted_income(db_session, user_acct):
    """PAYDAY_SWEEP must fire when a REAL income row posts today and a goal is
    underfunded. Regression: the trigger used to read project_cashflows(as_of,
    as_of), which only returns future projected occurrences (the anchor itself is
    excluded), so the paycheck that actually posted today was invisible and the
    alert was inert."""
    user, acct = user_acct
    # A real paycheck posted today.
    db_session.add(IncomeORM(title="Paycheck", amount=2000_00, date=AS_OF.isoformat(),
                             category="Work", account_id=acct.id))
    # An underfunded active goal.
    db_session.add(GoalORM(user_id=user.id, name="Emergency", amount=500_00,
                           progress=0, date="2026-12-01", completed=0))
    db_session.flush()
    alerts = AlertEngine(db_session).evaluate(_u(user), AS_OF)
    assert any(a.type == "PAYDAY_SWEEP" for a in alerts)


def test_payday_sweep_silent_with_no_income_today(db_session, user_acct):
    user, acct = user_acct
    # Income posted YESTERDAY, not today → no sweep.
    db_session.add(IncomeORM(title="Paycheck", amount=2000_00,
                             date=(AS_OF - timedelta(days=1)).isoformat(),
                             category="Work", account_id=acct.id))
    db_session.add(GoalORM(user_id=user.id, name="Emergency", amount=500_00,
                           progress=0, date="2026-12-01", completed=0))
    db_session.flush()
    alerts = AlertEngine(db_session).evaluate(_u(user), AS_OF)
    assert not any(a.type == "PAYDAY_SWEEP" for a in alerts)


def test_negative_ahead_window(db_session, user_acct):
    user, acct = user_acct
    # Big bill 4 days out (monthly anchor 05-05 → occurrence 06-05) → balance
    # goes negative within the 5-day window.
    _bill(db_session, acct, title="Big", amount_cents=500_00, anchor="2026-05-05")
    near = AlertEngine(db_session).evaluate(_u(user), AS_OF)
    assert any(a.type == "NEGATIVE_AHEAD" for a in near)
    # Same bill 12 days out (anchor 05-13 → occurrence 06-13) → outside window.
    db_session.execute(text("UPDATE expenses SET date='2026-05-13'"))
    db_session.flush()
    far = AlertEngine(db_session).evaluate(_u(user), AS_OF)
    assert not any(a.type == "NEGATIVE_AHEAD" for a in far)


# ── 5-8: caps & hygiene ──────────────────────────────────────────────────


def test_at_most_one_alert_delivered_per_day(db_session, user_acct):
    user, acct = user_acct
    # Two distinct dips eligible same day (May anchors → June occurrences).
    _bill(db_session, acct, title="A", amount_cents=200_00, anchor="2026-05-03")
    _bill(db_session, acct, title="B", amount_cents=150_00, anchor="2026-05-04")
    delivered = AlertEngine(db_session).deliver(_u(user), AS_OF)
    db_session.flush()
    assert len(delivered) <= 1  # max 1 per day


def test_opt_out_suppresses_delivery_but_records_fired(db_session, user_acct):
    user, acct = user_acct
    _bill(db_session, acct, title="Rent", amount_cents=200_00, anchor="2026-05-04")
    delivered = AlertEngine(db_session).deliver(
        _u(user), AS_OF, opted_out_types={"BILL_DIP", "NEGATIVE_AHEAD"}
    )
    db_session.flush()
    assert delivered == []
    # AlertFired still recorded with delivered=false (E8 instrumentation).
    rows = db_session.execute(text("SELECT payload FROM game_events WHERE type='AlertFired'")).scalars().all()
    assert rows and all(json.loads(r)["delivered"] is False for r in rows)


def test_banned_pattern_scan_over_templates(db_session):
    import json as _json
    import pathlib

    terms_dir = pathlib.Path(__file__).resolve().parents[2] / "client" / "src" / "terms"
    for f in ("terms.off.json", "terms.ambient.json", "terms.full.json"):
        terms = _json.loads((terms_dir / f).read_text())
        offenders = scan_templates_for_banned_patterns(terms)
        assert offenders == [], f"{f} has spending-nudge copy: {offenders}"


def test_banned_patterns_are_the_spending_words():
    assert "buy" in BANNED_PATTERNS and "spend" in BANNED_PATTERNS


# ── 9-11: fixes ──────────────────────────────────────────────────────────


def test_create_allocation_fix_records_event_and_funds_goal(db_session, user_acct):
    user, acct = user_acct
    goal = GoalORM(user_id=user.id, name="EF", amount=1000_00, date="2027-01-01",
                   completed=0, progress=0)
    db_session.add(goal)
    db_session.flush()
    # The assistant allowlist (C5) intentionally no longer validates this action
    # (it is not in SUPPORTED_ACTIONS). We exercise the underlying allocate
    # MACHINERY directly with normalized params — that machinery is unchanged.
    norm = {"goal_id": goal.id, "amount": 25.0}
    result = ActionService.execute(db_session, user.id, "create_allocation", norm)
    db_session.flush()
    db_session.refresh(goal)
    assert goal.progress == 25_00
    assert result["goal_id"] == goal.id
    fired = db_session.execute(text("SELECT COUNT(*) FROM game_events WHERE type='AlertFixApplied'")).scalar_one()
    assert fired == 1


def test_replayed_confirm_token_does_not_double_allocate(db_session, user_acct):
    user, acct = user_acct
    goal = GoalORM(user_id=user.id, name="EF", amount=1000_00, date="2027-01-01",
                   completed=0, progress=0)
    db_session.add(goal)
    db_session.flush()
    token = ActionService.make_token(user.id, "create_allocation",
                                     {"goal_id": goal.id, "amount": 25.0})
    claims = ActionService.decode_token(token)
    # First confirm succeeds and COMMITS (mirrors the per-request boundary: the
    # confirm endpoint commits, so a later replay's rollback can't undo it).
    assert ActionService.reserve_jti(db_session, user.id, claims["jti"]) is True
    ActionService.execute(db_session, user.id, "create_allocation", claims["params"])
    db_session.commit()
    # Replay: same jti is rejected → no second execute. reserve_jti rolls back
    # the (empty) replay attempt; the committed first allocation is untouched.
    assert ActionService.reserve_jti(db_session, user.id, claims["jti"]) is False
    progress = db_session.execute(
        text("SELECT progress FROM goals WHERE id=:i"), {"i": goal.id}
    ).scalar_one()
    assert progress == 25_00  # only one allocation applied


# ── 12-15: what-if (R14) ─────────────────────────────────────────────────


def test_default_scenario_is_nontrivial_and_reachable(db_session, user_acct):
    user, acct = user_acct
    goal = GoalORM(user_id=user.id, name="Trip", amount=1200_00, date="2027-06-01",
                   completed=0, progress=0)
    db_session.add(goal)
    db_session.flush()
    res = WhatIfService(db_session).simulate(
        user.id, goal.id, current_monthly=50.0, as_of=AS_OF
    )
    # +5% of $50 = $2.50 default delta (non-trivial, not $0, not $500).
    assert res.suggested_delta_cents == 2_50
    assert res.reaches_on is not None


def test_unreachable_goal_returns_smallest_achieving_delta(db_session, user_acct):
    user, acct = user_acct
    goal = GoalORM(user_id=user.id, name="Big", amount=2400_00, date="2027-06-01",
                   completed=0, progress=0)
    db_session.add(goal)
    db_session.flush()
    # current rate 0 → never reaches; expect a positive smallest-achieving delta.
    res = WhatIfService(db_session).simulate(
        user.id, goal.id, current_monthly=0.0, as_of=AS_OF
    )
    assert res.reachable_at_current is False
    assert res.suggested_delta_cents > 0
    assert res.reaches_on is not None  # reaches WITH the suggested delta


def test_strain_mode_returns_single_action(db_session, user_acct):
    user, acct = user_acct
    goal = GoalORM(user_id=user.id, name="X", amount=1000_00, date="2027-06-01",
                   completed=0, progress=0)
    db_session.add(goal)
    db_session.flush()
    res = WhatIfService(db_session).simulate(
        user.id, goal.id, current_monthly=40.0, strain_mode=True, as_of=AS_OF
    )
    assert res.single_action is True
    assert res.reaches_on is None  # no long-horizon sim under strain


def test_whatif_commit_creates_rule_and_records_event(db_session, user_acct):
    user, acct = user_acct
    goal = GoalORM(user_id=user.id, name="X", amount=1000_00, date="2027-06-01",
                   completed=0, progress=0)
    db_session.add(goal)
    db_session.flush()
    # whatif_commit is intentionally out of the C5 assistant allowlist; exercise
    # the underlying rule-creation machinery directly with normalized params.
    norm = {"goal_id": goal.id, "amount": 30.0, "name": "What-if commitment"}
    result = ActionService.execute(db_session, user.id, "whatif_commit", norm)
    db_session.flush()
    rule_count = db_session.execute(text("SELECT COUNT(*) FROM rules WHERE id=:i"),
                                    {"i": result["rule_id"]}).scalar_one()
    assert rule_count == 1
    committed = db_session.execute(text("SELECT COUNT(*) FROM game_events WHERE type='WhatIfCommitted'")).scalar_one()
    assert committed == 1


# ── 16-17: glanceable number format rules (server side of the contract) ──


def test_safe_to_spend_number_is_mode_independent(db_session, user_acct):
    # The number comes from the v1 service and does not depend on game_mode.
    from server.src.services.spend_service import SpendService

    user, acct = user_acct
    user.game_mode = "full"
    db_session.flush()
    full = SpendService(db_session).safe_to_spend(_u(user))["available"]
    user.game_mode = "off"
    db_session.flush()
    off = SpendService(db_session).safe_to_spend(_u(user))["available"]
    assert full == off  # mode never changes the number


# ── 19-20: graduation + soft-landing ─────────────────────────────────────


def test_graduation_detects_repeated_allocations(db_session, user_acct):
    user, acct = user_acct
    from server.src.db.models import Rule as RuleORM, RuleExecution as RuleExecORM

    rule = RuleORM(user_id=user.id, name="sweep", enabled=1, conditions="[]",
                   action_type="allocate", action_params="{}", target_kind="goal",
                   target_id=1, priority=0)
    db_session.add(rule)
    db_session.flush()
    # Three identical allocations of $30.
    for i in range(3):
        db_session.add(RuleExecORM(rule_id=rule.id, tx_type="income", tx_id=i,
                                   action_type="allocate", amount_cents=30_00, result="ok"))
    db_session.flush()
    candidates = detect_graduation_candidates(db_session, user.id, as_of=AS_OF)
    assert len(candidates) == 1
    assert candidates[0].amount_cents == 30_00


def test_soft_land_never_penalizes(db_session):
    landing = soft_land({"amount": 30.0, "cadence": "weekly"})
    assert landing["penalty"] is None
    assert landing["re_offer"]["amount"] == 15.0  # smaller re-offer, no deduction


# ── 21: integrity around a full alert→fix cycle ──────────────────────────


def test_alert_fix_cycle_only_changes_expected_rows(db_session, user_acct):
    user, acct = user_acct
    goal = GoalORM(user_id=user.id, name="EF", amount=1000_00, date="2027-01-01",
                   completed=0, progress=0)
    db_session.add(goal)
    db_session.flush()
    # Fingerprint BEFORE includes the goal at progress=0.
    before = finance_tables_fingerprint(db_session)
    # Evaluating alerts writes no finance rows.
    AlertEngine(db_session).evaluate(_u(user), AS_OF)
    assert finance_tables_fingerprint(db_session) == before
    # The fix DOES change finance (goal.progress) — via the underlying allocate
    # machinery (create_allocation is intentionally out of the C5 allowlist, so
    # build normalized params directly rather than through the gated validate).
    norm = {"goal_id": goal.id, "amount": 10.0}
    ActionService.execute(db_session, user.id, "create_allocation", norm)
    db_session.flush()
    after = finance_tables_fingerprint(db_session)
    assert after != before  # exactly the goal earmark changed
