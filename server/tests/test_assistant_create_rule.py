"""NL→rule authoring (Pillar 2A) end-to-end tests.

The same propose→confirm gate as every other write action: the tool only
PROPOSES a rule; the ``Rule`` row is created only after an explicit confirm.
These run via the API (no Groq) plus the validate layer directly.
"""

from sqlalchemy import select

from server.src.db.models import Goal as GoalORM, Rule as RuleORM
from server.src.services.assistant_service import (
    ActionService,
    ActionError,
    SUPPORTED_ACTIONS,
    _HANDLED,
)
import pytest


def _auth_header(client, username="cruser", email="cr@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "CR User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _make_goal(client, headers, name="House fund"):
    resp = client.post(
        "/api/goals/",
        json={
            "name": name,
            "description": "",
            "amount": 10000.0,
            "date": "2028-01-01",
            "completed": False,
            "progress": 0.0,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return client.get("/api/goals/", headers=headers).json()[-1]["id"]


# ── The pinned anti-drift invariant ──────────────────────────────────────────


def test_create_rule_is_in_both_action_sets():
    assert "create_rule" in SUPPORTED_ACTIONS
    assert _HANDLED == set(SUPPORTED_ACTIONS)


# ── Validate-layer shape checks ──────────────────────────────────────────────


def test_validate_allocate_shape():
    norm, summary = ActionService.validate(
        "create_rule",
        {
            "action_type": "allocate",
            "name": "House fund",
            "target_id": 7,
            "amount": 50,
            "conditions": [{"field": "type", "op": "eq", "value": "income"}],
        },
    )
    assert norm["action_type"] == "allocate"
    assert norm["amount"] == 50.0
    assert norm["target_id"] == 7
    assert "$50.00" in summary


def test_validate_rejects_bad_action_type():
    with pytest.raises(ActionError):
        ActionService.validate("create_rule", {"action_type": "roundup", "name": "x"})


def test_validate_rejects_malformed_condition():
    with pytest.raises(ActionError):
        ActionService.validate(
            "create_rule",
            {
                "action_type": "notify",
                "name": "x",
                "conditions": [{"field": "bogus", "op": "eq", "value": 1}],
            },
        )


def test_validate_rejects_nonpositive_allocate_amount():
    with pytest.raises(ActionError):
        ActionService.validate(
            "create_rule",
            {"action_type": "allocate", "name": "x", "target_id": 1, "amount": 0},
        )


def test_validate_rejects_allocate_with_no_conditions():
    """An allocate rule with no trigger would fire on every transaction."""
    with pytest.raises(ActionError):
        ActionService.validate(
            "create_rule",
            {"action_type": "allocate", "name": "x", "target_id": 1, "amount": 50, "conditions": []},
        )


def test_validate_rejects_null_amount_value():
    with pytest.raises(ActionError):
        ActionService.validate(
            "create_rule",
            {
                "action_type": "notify",
                "name": "x",
                "conditions": [{"field": "amount", "op": "gt", "value": None}],
            },
        )


def test_validate_rejects_string_for_in_list():
    with pytest.raises(ActionError):
        ActionService.validate(
            "create_rule",
            {
                "action_type": "notify",
                "name": "x",
                "conditions": [{"field": "category", "op": "in", "value": "Food"}],
            },
        )


def test_validate_accepts_in_list():
    norm, _ = ActionService.validate(
        "create_rule",
        {
            "action_type": "notify",
            "name": "x",
            "conditions": [{"field": "category", "op": "in", "value": ["Food", "Travel"]}],
        },
    )
    assert norm["conditions"][0]["value"] == ["Food", "Travel"]


def test_validate_rejects_bad_type_value():
    with pytest.raises(ActionError):
        ActionService.validate(
            "create_rule",
            {
                "action_type": "notify",
                "name": "x",
                "conditions": [{"field": "type", "op": "eq", "value": "transfer"}],
            },
        )


# ── Propose → confirm end to end ─────────────────────────────────────────────


def test_propose_does_not_create_rule(client, db_session):
    headers = _auth_header(client)
    goal_id = _make_goal(client, headers)
    resp = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "create_rule",
            "params": {
                "action_type": "allocate",
                "name": "Payday savings",
                "target_id": goal_id,
                "amount": 50,
                "conditions": [{"field": "type", "op": "eq", "value": "income"}],
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["token"]
    assert db_session.execute(select(RuleORM)).scalars().all() == []


def test_confirm_creates_allocate_rule(client, db_session):
    headers = _auth_header(client)
    goal_id = _make_goal(client, headers)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "create_rule",
            "params": {
                "action_type": "allocate",
                "name": "Payday savings",
                "target_id": goal_id,
                "amount": 50,
                "conditions": [{"field": "type", "op": "eq", "value": "income"}],
            },
        },
        headers=headers,
    ).json()
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    db_session.expire_all()
    rule = db_session.execute(select(RuleORM)).scalar_one()
    assert rule.action_type == "allocate"
    assert rule.target_kind == "goal"
    assert rule.target_id == goal_id
    assert '"amount": 50' in rule.action_params
    assert rule.enabled == 1


def test_confirm_creates_notify_rule(client, db_session):
    headers = _auth_header(client)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "create_rule",
            "params": {
                "action_type": "notify",
                "name": "Big dining",
                "message": "Large dining charge",
                "conditions": [
                    {"field": "category", "op": "eq", "value": "Food"},
                    {"field": "amount", "op": "gt", "value": 100},
                ],
            },
        },
        headers=headers,
    ).json()
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    db_session.expire_all()
    rule = db_session.execute(select(RuleORM)).scalar_one()
    assert rule.action_type == "notify"
    assert rule.target_id is None
    assert "Large dining charge" in rule.action_params


def test_confirm_replay_is_rejected(client, db_session):
    headers = _auth_header(client)
    goal_id = _make_goal(client, headers)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "create_rule",
            "params": {
                "action_type": "allocate",
                "name": "Payday savings",
                "target_id": goal_id,
                "amount": 50,
                "conditions": [{"field": "type", "op": "eq", "value": "income"}],
            },
        },
        headers=headers,
    ).json()
    first = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert first.status_code == 200
    replay = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert replay.status_code == 409  # one-use token


def test_confirm_rejects_foreign_goal(client, db_session):
    """An allocate rule whose goal was deleted (or never owned) must fail at confirm."""
    headers = _auth_header(client)
    goal_id = _make_goal(client, headers)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "create_rule",
            "params": {
                "action_type": "allocate",
                "name": "Payday savings",
                "target_id": goal_id,
                "amount": 50,
                "conditions": [{"field": "type", "op": "eq", "value": "income"}],
            },
        },
        headers=headers,
    ).json()
    # Delete the goal between propose and confirm.
    assert client.delete(f"/api/goals/{goal_id}/", headers=headers).status_code in (200, 204)
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 400  # target goal not found
