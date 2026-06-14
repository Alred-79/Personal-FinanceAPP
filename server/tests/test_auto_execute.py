"""Pillar 2B — bounded auto-execute, end to end through the API.

An above-threshold auto-fund rule firing surfaces a durable ``rule_proposal``
notification (NOT a silent earmark). The user re-mints a one-tap confirm token
from that notification and approves it through the normal confirm endpoint, which
funds the goal's virtual earmark — and only then does money "move" (virtually).
Replay-guarded and ownership-checked like every other write.
"""

import json

from sqlalchemy import select

from server.src.db.models import (
    Goal as GoalORM,
    Notification as NotificationORM,
    Rule as RuleORM,
    User as UserORM,
)
from server.src.services.assistant_service import SUPPORTED_ACTIONS, _HANDLED


def _auth_header(client, username="aeuser", email="ae@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "AE User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _make_account(client, headers):
    client.post(
        "/api/accounts/",
        json={"name": "Manual", "type": "checking", "balance": 0.0},
        headers=headers,
    )
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


def _make_goal(client, headers, name="House"):
    client.post(
        "/api/goals/",
        json={
            "name": name,
            "description": "",
            "amount": 100000.0,
            "date": "2030-01-01",
            "completed": False,
            "progress": 0.0,
        },
        headers=headers,
    )
    return client.get("/api/goals/", headers=headers).json()[-1]["id"]


# ── Pinned-set invariant (R5) ────────────────────────────────────────────────


def test_create_allocation_is_in_both_action_sets():
    """2B moved create_allocation into both sets as a pair; the equality test
    auto-catches a one-sided edit, this asserts the membership explicitly."""
    assert "create_allocation" in SUPPORTED_ACTIONS
    assert _HANDLED == set(SUPPORTED_ACTIONS)


# ── End to end: above-threshold firing → notification → re-mint → confirm ─────


def test_above_threshold_firing_surfaces_proposal_then_confirms(client, db_session):
    headers = _auth_header(client)
    acct_id = _make_account(client, headers)
    goal_id = _make_goal(client, headers)

    # Lower this user's threshold to $100 (the default) explicitly.
    user = db_session.execute(
        select(UserORM).where(UserORM.username == "aeuser")
    ).scalar_one()
    user.auto_execute_threshold_cents = 10000
    db_session.flush()

    # A standing allocate rule that sets aside $250 on income (above $100).
    rule = RuleORM(
        user_id=user.id,
        name="Big payday savings",
        enabled=1,
        conditions=json.dumps([{"field": "type", "op": "eq", "value": "income"}]),
        action_type="allocate",
        action_params=json.dumps({"amount": 250.0}),
        target_kind="goal",
        target_id=goal_id,
        priority=0,
    )
    db_session.add(rule)
    db_session.commit()

    # Record an income transaction → the rule fires above threshold.
    resp = client.post(
        "/api/income/",
        json={
            "title": "Paycheck",
            "amount": 5000.0,
            "date": "2026-06-01",
            "category": "Income",
            "account_id": acct_id,
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text

    # The earmark did NOT move; a proposal notification appeared instead.
    db_session.expire_all()
    goal = db_session.execute(
        select(GoalORM).where(GoalORM.id == goal_id)
    ).scalar_one()
    assert goal.progress == 0

    note = db_session.execute(
        select(NotificationORM).where(
            NotificationORM.user_id == user.id,
            NotificationORM.type == "rule_proposal",
        )
    ).scalar_one()

    # Re-mint a fresh one-tap confirm token from the notification.
    mint = client.post(
        f"/api/notifications/{note.id}/proposal-token/", headers=headers
    )
    assert mint.status_code == 200, mint.text
    token = mint.json()["token"]
    assert mint.json()["amount"] == 250.0

    # Approve it through the normal confirm endpoint → the earmark now moves.
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": token},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    db_session.expire_all()
    goal = db_session.execute(
        select(GoalORM).where(GoalORM.id == goal_id)
    ).scalar_one()
    assert goal.progress == 25000  # $250 finally earmarked, after approval


def test_proposal_token_rejects_foreign_or_deleted_goal(client, db_session):
    headers = _auth_header(client)
    goal_id = _make_goal(client, headers)
    user = db_session.execute(
        select(UserORM).where(UserORM.username == "aeuser")
    ).scalar_one()
    # Hand-craft a proposal notification, then delete the goal.
    note = NotificationORM(
        user_id=user.id,
        type="rule_proposal",
        title="x",
        message="x",
        ref=f"rule_proposal:1:{goal_id}:25000",
    )
    db_session.add(note)
    db_session.commit()
    assert client.delete(f"/api/goals/{goal_id}/", headers=headers).status_code in (
        200,
        204,
    )
    resp = client.post(
        f"/api/notifications/{note.id}/proposal-token/", headers=headers
    )
    assert resp.status_code == 404


def test_proposal_token_rejects_non_proposal_notification(client, db_session):
    headers = _auth_header(client)
    user = db_session.execute(
        select(UserORM).where(UserORM.username == "aeuser")
    ).scalar_one()
    note = NotificationORM(
        user_id=user.id, type="anomaly", title="x", message="x", ref="anomaly:1"
    )
    db_session.add(note)
    db_session.commit()
    resp = client.post(
        f"/api/notifications/{note.id}/proposal-token/", headers=headers
    )
    assert resp.status_code == 400
