"""Completion audit tests, adversarial criteria.

These probe *completion* rather than happy-path behaviour:

* Cross user IDOR on the feature routers (budgets, notifications,
  subscriptions), a user must never reach another user's rows by id.
* Assistant action token edge cases the suite doesn't hit: an **expired**
  confirmation token and a **forged** one (signed with the wrong key).

All run against the API via the shared in memory engine `client` fixture.
"""

from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

import pytest
from fastapi import HTTPException

from server.src.db.models import (
    Budget as BudgetORM,
    Notification as NotificationORM,
    RefreshToken as RefreshTokenORM,
    User as UserORM,
)
from server.src.services.assistant_service import _ACTION_TOKEN_TYPE
from server.src.services.auth_service import AuthService
from server.src.settings import settings


# ── Helpers ──────────────────────────────────────────────────────────────────


def _signup(client, username, email):
    """Sign up a user and return a Bearer auth header (cookies cleared)."""
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": username.title(),
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _uid(db_session, username):
    return db_session.execute(
        select(UserORM.id).where(UserORM.username == username)
    ).scalar_one()


# ── Cross user IDOR: budgets ─────────────────────────────────────────────────


def test_budget_update_cross_user_rejected(client, db_session):
    """User B must not be able to update User A's budget by id."""
    a = _signup(client, "alice", "alice@example.com")
    b = _signup(client, "bob", "bob@example.com")

    assert client.post(
        "/api/budgets/",
        json={"category": "Food", "monthly_limit": 300.0, "rollover": False},
        headers=a,
    ).status_code == 200

    budget_id = db_session.execute(
        select(BudgetORM.id).where(BudgetORM.user_id == _uid(db_session, "alice"))
    ).scalar_one()

    resp = client.put(
        f"/api/budgets/{budget_id}/",
        json={"category": "Food", "monthly_limit": 1.0, "rollover": False},
        headers=b,
    )
    assert resp.status_code == 404, resp.text

    # A's budget is unchanged (still 300.00 → 30000 cents).
    db_session.expire_all()
    limit = db_session.execute(
        select(BudgetORM.monthly_limit).where(BudgetORM.id == budget_id)
    ).scalar_one()
    assert limit == 30000


def test_budget_delete_cross_user_rejected(client, db_session):
    a = _signup(client, "alice", "alice@example.com")
    b = _signup(client, "bob", "bob@example.com")

    assert client.post(
        "/api/budgets/",
        json={"category": "Rent", "monthly_limit": 1500.0, "rollover": False},
        headers=a,
    ).status_code == 200
    budget_id = db_session.execute(
        select(BudgetORM.id).where(BudgetORM.user_id == _uid(db_session, "alice"))
    ).scalar_one()

    resp = client.delete(f"/api/budgets/{budget_id}/", headers=b)
    assert resp.status_code == 404, resp.text

    # Still present.
    db_session.expire_all()
    assert db_session.execute(
        select(BudgetORM.id).where(BudgetORM.id == budget_id)
    ).scalar_one_or_none() is not None


# ── Cross user IDOR: notifications ───────────────────────────────────────────


def test_notification_mark_read_cross_user_rejected(client, db_session):
    """User B must not mark User A's notification as read."""
    _ = _signup(client, "alice", "alice@example.com")
    b = _signup(client, "bob", "bob@example.com")

    notif = NotificationORM(
        user_id=_uid(db_session, "alice"),
        type="budget_overrun",
        title="Over budget",
        message="You exceeded your Food budget.",
        ref="food-2026-05",
        read=0,
    )
    db_session.add(notif)
    db_session.commit()
    notif_id = notif.id

    resp = client.put(f"/api/notifications/{notif_id}/read/", headers=b)
    assert resp.status_code == 404, resp.text

    # Still unread for A.
    db_session.expire_all()
    assert db_session.execute(
        select(NotificationORM.read).where(NotificationORM.id == notif_id)
    ).scalar_one() == 0


# ── Cross user isolation: subscriptions list ─────────────────────────────────


def test_subscriptions_isolated_between_users(client, db_session):
    a = _signup(client, "alice", "alice@example.com")
    b = _signup(client, "bob", "bob@example.com")

    # Bob has no data → his subscriptions list must be empty regardless of A.
    resp = client.get("/api/subscriptions/", headers=b)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []

    # A's list is also independent (no crash on empty).
    assert client.get("/api/subscriptions/", headers=a).status_code == 200


# ── Assistant action token: expired ──────────────────────────────────────────


def _make_action_token(uid, action, params, *, exp_delta, key=None):
    payload = {
        "uid": int(uid),
        "typ": _ACTION_TOKEN_TYPE,
        "jti": "audit-" + str(uid) + action,
        "action": action,
        "params": params,
        "exp": datetime.now(timezone.utc) + exp_delta,
    }
    return jwt.encode(
        payload,
        key or settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def test_expired_action_token_rejected(client, db_session):
    """A correctly signed but expired confirmation token must not execute."""
    headers = _signup(client, "carol", "carol@example.com")
    uid = _uid(db_session, "carol")

    token = _make_action_token(
        uid,
        "add_goal",
        {"name": "Vacation", "amount": 1000.0, "date": "2027-01-01"},
        exp_delta=timedelta(minutes=-1),  # already expired
    )
    resp = client.post(
        "/api/assistant/actions/confirm/", json={"token": token}, headers=headers
    )
    assert resp.status_code >= 400, resp.text
    # No goal was created.
    from server.src.db.models import Goal as GoalORM

    db_session.expire_all()
    assert db_session.execute(
        select(GoalORM).where(GoalORM.user_id == uid)
    ).scalars().all() == []


# ── Refresh token reuse detection (family revocation) ────────────────────────


def test_refresh_token_reuse_revokes_family(db_session):
    """Replaying an already rotated refresh token must kill the whole family.

    RFC 6819 reuse detection: if a revoked token is presented again (theft
    signal), every active token for that user, including the one minted by the
    legitimate rotation, must be revoked so the attacker's session dies too.
    """
    user = UserORM(
        username="erin",
        full_name="Erin",
        email="erin@example.com",
        hashed_password="x",
        disabled=0,
    )
    db_session.add(user)
    db_session.flush()

    # Issue → rotate once. raw2 is now the active token; raw1 is revoked.
    raw1 = AuthService.create_refresh_token(db_session, user.id)
    db_session.commit()
    raw2, _user = AuthService.rotate_refresh_token(db_session, raw1)
    db_session.commit()

    # Replay the OLD (revoked) token → reuse detected → 401 + family revoked.
    with pytest.raises(HTTPException) as exc1:
        AuthService.rotate_refresh_token(db_session, raw1)
    assert exc1.value.status_code == 401

    # The legitimately rotated token (raw2) must now also be dead.
    with pytest.raises(HTTPException) as exc2:
        AuthService.rotate_refresh_token(db_session, raw2)
    assert exc2.value.status_code == 401

    # Every refresh token for this user is revoked.
    db_session.expire_all()
    active = db_session.execute(
        select(RefreshTokenORM).where(
            RefreshTokenORM.user_id == user.id,
            RefreshTokenORM.revoked == 0,
        )
    ).scalars().all()
    assert active == []


def test_forged_action_token_rejected(client, db_session):
    """A token signed with the wrong key must be rejected."""
    headers = _signup(client, "dave", "dave@example.com")
    uid = _uid(db_session, "dave")

    token = _make_action_token(
        uid,
        "add_goal",
        {"name": "Forged", "amount": 5.0, "date": "2027-01-01"},
        exp_delta=timedelta(minutes=10),
        key="not-the-real-signing-key",
    )
    resp = client.post(
        "/api/assistant/actions/confirm/", json={"token": token}, headers=headers
    )
    assert resp.status_code >= 400, resp.text

    from server.src.db.models import Goal as GoalORM

    db_session.expire_all()
    assert db_session.execute(
        select(GoalORM).where(GoalORM.user_id == uid)
    ).scalars().all() == []
