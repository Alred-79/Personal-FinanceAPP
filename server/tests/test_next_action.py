"""W8 — Neurodivergent mode: the unified "one thing today" ranker + grace widening.

Covers the W8 spec test cases:
  * the ranker picks the SINGLE highest-value action (strict priority across
    bridges, rule proposals, challenges, streak recovery, auditor findings);
  * exactly ONE action is returned even when many sources are live;
  * the empty state returns a calm "all set" and NEVER invents a task;
  * grace params are RESPECTED (widened) under ``neurodivergent_mode`` and identical
    to baseline when the flag is off — and the widening SOFT-LANDS (only ever adds a
    Grace episode, never voids one / disables a verdict);
  * the endpoint works with the flag OFF (B4 ship-dark);
  * the flag is surfaced to the client via ``GET /settings/`` features.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from server.src.db.models import (
    Account as AccountORM,
    AssistedAction as AssistedActionORM,
    Challenge as ChallengeORM,
    Notification as NotificationORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services import next_action as na
from server.src.services.game import grace as grace_mod
from server.src.settings import settings

_TODAY = date(2026, 6, 15)


# ── helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture
def user_acct(db_session):
    u = UserORM(username="nd", full_name="ND U", email="nd@x.com", hashed_password="x",
                savings_percent=0)
    db_session.add(u)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=500_00, user_id=u.id)
    db_session.add(acct)
    db_session.flush()
    return u, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


def _bridge(db, user_id, *, amount=200_00, created=None, status="proposed"):
    b = AssistedActionORM(
        user_id=user_id, kind="transfer", amount_cents=amount,
        rationale="Move money toward the plan.", how_json="{}", status=status,
        verify_ref=f"vr:{user_id}:{amount}:{created}",
        created_at=(created or _TODAY).isoformat(),
    )
    db.add(b)
    db.flush()
    return b


def _proposal(db, user_id, *, read=0):
    n = NotificationORM(
        user_id=user_id, type="rule_proposal",
        title="Auto-fund proposal", message="Set aside $50 toward your goal.",
        ref=f"rule_proposal:1:1:5000", read=read,
    )
    db.add(n)
    db.flush()
    return n


def _challenge(db, user_id, *, ends_in_days=2):
    c = ChallengeORM(
        user_id=user_id, key="t1_category_free_week", tier=1, category="dining",
        status="active", starts_on=(_TODAY - timedelta(days=5)).isoformat(),
        ends_on=(_TODAY + timedelta(days=ends_in_days)).isoformat(),
        params_json="{}",
    )
    db.add(c)
    db.flush()
    return c


def _auditor_note(db, user_id):
    n = NotificationORM(
        user_id=user_id, type="overdraft_risk",
        title="Overdraft risk", message="A small dip is possible before month end.",
        ref=f"audit:overdraft:{user_id}:2026-06", read=0,
    )
    db.add(n)
    db.flush()
    return n


# ── ranking: exactly one, strict priority ─────────────────────────────────────


def test_empty_state_returns_all_set_and_invents_nothing(db_session, user_acct):
    user, _ = user_acct
    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["has_action"] is False
    assert out["action_type"] == "all_set"
    assert out["entity_id"] is None
    assert "all set" in out["copy"].lower()


def test_bridge_outranks_everything(db_session, user_acct):
    """All five sources live at once → the bridge (top priority) is the one thing."""
    user, _ = user_acct
    bridge = _bridge(db_session, user.id)
    _proposal(db_session, user.id)
    _challenge(db_session, user.id)
    _auditor_note(db_session, user.id)

    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["has_action"] is True
    assert out["action_type"] == "bridge_due"
    assert out["entity_id"] == bridge.id


def test_proposal_outranks_challenge_and_auditor(db_session, user_acct):
    user, _ = user_acct
    note = _proposal(db_session, user.id)
    _challenge(db_session, user.id)
    _auditor_note(db_session, user.id)

    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["action_type"] == "rule_proposal"
    assert out["entity_id"] == note.id


def test_challenge_outranks_auditor(db_session, user_acct):
    user, _ = user_acct
    ch = _challenge(db_session, user.id, ends_in_days=1)
    _auditor_note(db_session, user.id)

    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["action_type"] == "challenge_ending"
    assert out["entity_id"] == ch.id


def test_challenge_not_ending_soon_is_skipped(db_session, user_acct):
    """A challenge far from its end date is NOT the one thing — falls to auditor."""
    user, _ = user_acct
    _challenge(db_session, user.id, ends_in_days=30)
    note = _auditor_note(db_session, user.id)

    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["action_type"] == "auditor_finding"
    assert out["entity_id"] == note.id


def test_auditor_finding_is_lowest_priority(db_session, user_acct):
    user, _ = user_acct
    note = _auditor_note(db_session, user.id)
    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["action_type"] == "auditor_finding"
    assert out["entity_id"] == note.id


def test_read_proposal_does_not_surface(db_session, user_acct):
    """A read proposal has been seen — it's not the pending one-tap thing."""
    user, _ = user_acct
    _proposal(db_session, user.id, read=1)
    note = _auditor_note(db_session, user.id)
    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["action_type"] == "auditor_finding"
    assert out["entity_id"] == note.id


def test_streak_recovery_outranks_auditor(db_session, user_acct):
    """A rebuilding streak surfaces a gentle recovery nudge above an auditor finding."""
    from server.src.services.game.daily import _state, _put, register_daily_folds

    user, _ = user_acct
    register_daily_folds()
    st = _state(db_session)
    st["status"] = "rebuilding"
    st["best"] = 7
    st["current"] = 0
    _put(db_session, st)
    db_session.flush()

    _auditor_note(db_session, user.id)
    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["action_type"] == "streak_recovery"
    # No-shame: never the word "broken" / "failed".
    low = out["copy"].lower()
    assert "broken" not in low and "fail" not in low


def test_copy_is_screened_no_shame(db_session, user_acct):
    """Every returned copy string is non-empty and free of the firewall placeholder."""
    user, _ = user_acct
    _bridge(db_session, user.id)
    out = na.compute(db_session, user.id, today=_TODAY)
    assert out["copy"]
    assert "can't help with that" not in out["copy"].lower()


# ── grace widening under the flag ─────────────────────────────────────────────


def test_grace_params_baseline_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "neurodivergent_mode", False)
    p = grace_mod.grace_params()
    assert p.negative_horizon_days == grace_mod.NEGATIVE_HORIZON_DAYS
    assert p.income_floor_ratio == grace_mod.INCOME_FLOOR_RATIO
    assert p.essential_shock_multiple == grace_mod.ESSENTIAL_SHOCK_MULTIPLE


def test_grace_params_widened_under_flag(monkeypatch):
    monkeypatch.setattr(settings, "neurodivergent_mode", True)
    p = grace_mod.grace_params()
    # Widened = MORE generous: higher income floor ratio, longer horizon, lower
    # essential-shock multiple — Grace eases off sooner.
    assert p.income_floor_ratio > grace_mod.INCOME_FLOOR_RATIO
    assert p.negative_horizon_days > grace_mod.NEGATIVE_HORIZON_DAYS
    assert p.essential_shock_multiple < grace_mod.ESSENTIAL_SHOCK_MULTIPLE


def test_grace_widening_soft_lands_only_adds_episodes(db_session, user_acct, monkeypatch):
    """Widening can ADD a Grace trigger but never REMOVE one (soft-land, not void).

    Seed a borderline income dip (78% of baseline): baseline 70% floor → no
    income trigger; widened 85% floor → income trigger fires. The widened set of
    signals is a SUPERSET of the baseline set — Grace only ever eases more, never
    voiding a verdict.
    """
    from server.src.db.models import Expense as ExpenseORM, Income as IncomeORM

    user, acct = user_acct
    # An old expense makes the baseline high-confidence (≥6 weeks of history); the
    # confidence signal reads expense activity, so income alone isn't enough.
    db_session.add(ExpenseORM(title="Old", amount=100, date="2026-01-02",
                              category="Misc", account_id=acct.id))
    # Build a confident ~$1000/mo income baseline over the trailing months, then a
    # current-month dip to ~$780 (78% — between the 70% and 85% floors).
    for d in ("2026-03-05", "2026-04-05", "2026-05-05"):
        db_session.add(IncomeORM(title="Pay", amount=1000_00, date=d, category="Salary", account_id=acct.id))
    db_session.add(IncomeORM(title="Pay", amount=780_00, date="2026-06-05", category="Salary", account_id=acct.id))
    db_session.flush()

    svc = grace_mod.GraceService(db_session)

    monkeypatch.setattr(settings, "neurodivergent_mode", False)
    base_signals = svc.evaluate(_u(user), _TODAY)

    monkeypatch.setattr(settings, "neurodivergent_mode", True)
    wide_signals = svc.evaluate(_u(user), _TODAY)

    # Baseline: 78% > 70% floor → income trigger does NOT fire.
    assert base_signals.income_below_floor is False
    # Widened: 78% < 85% floor → income trigger DOES fire (eases sooner).
    assert wide_signals.income_below_floor is True
    # Soft-land superset: every baseline trigger still holds under widening.
    for field in ("will_go_negative", "income_below_floor", "essential_shock", "sts_below_floor"):
        if getattr(base_signals, field):
            assert getattr(wide_signals, field), f"widening voided {field}"


# ── endpoint: works flag-off (B4); flag surfaced to client ────────────────────


def _auth_header(client, username="ndr", email="ndr@x.com"):
    resp = client.post(
        "/api/signup/",
        json={"username": username, "email": email, "full_name": "ND R",
              "password": "Test-password1"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_endpoint_works_with_flag_off(client, monkeypatch):
    """B4: the endpoint returns the ranked action regardless of the flag."""
    monkeypatch.setattr(settings, "neurodivergent_mode", False)
    headers = _auth_header(client)
    r = client.get("/api/next-action/", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action_type"] == "all_set"  # fresh user → nothing actionable
    assert body["has_action"] is False


def test_flag_surfaced_in_settings_features(client, monkeypatch):
    monkeypatch.setattr(settings, "neurodivergent_mode", True)
    headers = _auth_header(client, username="ndf", email="ndf@x.com")
    r = client.get("/api/settings/", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["features"]["neurodivergent_mode"] is True
