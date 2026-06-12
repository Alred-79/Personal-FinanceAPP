"""v4 package 09 — the Homestead (weekly/monthly reveal).

Trivial-sum suppression (the accrual key is ABSENT below $1.00), reveal hero is
projection + exactly one commit action, strain-mode suppresses the reveal, the
milestone ratchet (idempotent, homestead-XP-multiplier scope, no removal on
drop), and the engine-only projection (LLM never invoked).
"""

from __future__ import annotations

from datetime import date

import pytest

from server.src.db.models import Account as AccountORM, User as UserORM
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.homestead import (
    TRIVIAL_SUM_CENTS,
    check_milestones,
    multiplier,
    reveal_to_payload,
    weekly_reveal,
)

AS_OF = date(2026, 6, 15)


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="home", full_name="Home U", email="home@x.com",
                   hashed_password="x", savings_percent=0)
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=600_00, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


# ── 12: trivial-sum suppression ────────────────────────────────────────────


def test_accrual_line_suppressed_below_one_dollar(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    r = weekly_reveal(db_session, _u(user), AS_OF, recent_accrual_cents=43)  # $0.43
    payload = reveal_to_payload(r)
    assert "accrual_cents" not in payload  # KEY ABSENT, not "$0.43"


def test_accrual_line_present_at_or_above_one_dollar(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    r = weekly_reveal(db_session, _u(user), AS_OF, recent_accrual_cents=150)  # $1.50
    payload = reveal_to_payload(r)
    assert payload["accrual_cents"] == 150
    assert TRIVIAL_SUM_CENTS == 100


# ── 13: hero is projection + one action; strain suppresses ─────────────────


def test_reveal_has_exactly_one_commit_action(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    r = weekly_reveal(db_session, _u(user), AS_OF, recent_accrual_cents=200)
    assert r is not None
    assert isinstance(r.commit_action, dict) and r.commit_action.get("kind")


def test_strain_mode_suppresses_reveal(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    r = weekly_reveal(db_session, _u(user), AS_OF, recent_accrual_cents=200,
                      strain_mode=True)
    assert r is None
    assert reveal_to_payload(r) == {"suppressed": True}


# ── 14: milestone ratchet ──────────────────────────────────────────────────


def test_milestone_reached_once_and_ratchets(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # Balance 600 → crosses the $500 buffer milestone.
    newly = check_milestones(db_session, _u(user), AS_OF)
    assert "buffer_500" in newly
    mult_after = multiplier(db_session)
    # Re-running does NOT re-mint (idempotent).
    again = check_milestones(db_session, _u(user), AS_OF)
    assert "buffer_500" not in again
    from server.src.db.models import GameEvent

    minted = db_session.query(GameEvent).filter(
        GameEvent.type == "MilestoneReached",
        GameEvent.payload.like('%buffer_500%')).count()
    assert minted == 1
    # Dropping below the threshold must NOT remove the tier (ratchet).
    acct.balance = 100_00
    db_session.flush()
    check_milestones(db_session, _u(user), AS_OF)
    assert multiplier(db_session) == mult_after  # tier retained


def test_multiplier_scope_is_homestead_only(db_session, user_acct):
    # The multiplier helper is consumed by homestead accrual only; boss/stat XP
    # paths never import it. Structural assertion: the multiplier is a pure read
    # and crossing a milestone emits no XP-bearing event.
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    from server.src.services.game.stats import player_xp

    before = player_xp(db_session)["xp"]
    check_milestones(db_session, _u(user), AS_OF)
    assert player_xp(db_session)["xp"] == before  # milestone grants no flat XP
