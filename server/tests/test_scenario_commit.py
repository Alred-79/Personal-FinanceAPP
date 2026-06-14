"""``scenario_commit`` assistant action tests (v6 doc 05).

Committing a saved scenario must, through the existing propose→confirm gate:
turn each allocation-shaped commitment into a standing ``allocate`` Rule, lock
one ``PlanOfRecord`` snapshot, and append exactly one ``WhatIfCommitted`` event
(+20 XP). Replaying the same confirm token is a 409 and creates no duplicate
rule / plan / event — the event's ``idempotency_key`` (keyed on ``plan_id``) is
the backstop behind the single-use jti.
"""

from sqlalchemy import func, select

from server.src.db.models import (
    GameEvent as GameEventORM,
    PlanOfRecord as PlanOfRecordORM,
    Rule as RuleORM,
)
from server.src.services.assistant_service import SUPPORTED_ACTIONS, _HANDLED
from server.src.services.game.stats import player_xp


# ── Helpers ──────────────────────────────────────────────────────────────────


def _auth_header(client, username="scuser", email="sc@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "SC User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _create_goal(client, headers, amount=1000.00):
    resp = client.post(
        "/api/goals/",
        json={
            "name": "Emergency Fund",
            "description": "",
            "amount": amount,
            "date": "2027-06-01",
            "progress": 0,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # The create endpoint returns only a message; read the id back from the list.
    goals = client.get("/api/goals/", headers=headers).json()
    return goals[-1]["id"]


def _create_scenario(client, headers, goal_id, monthly=200.00):
    """A scenario whose single allocation-shaped commitment funds ``goal_id``."""
    resp = client.post(
        "/api/scenarios/",
        json={
            "name": "Fund the fund",
            "overlay": {"goal_mutations": [{"goal_id": goal_id, "amount": monthly}]},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _propose_commit(client, headers, scenario_id, name="My standing plan"):
    resp = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "scenario_commit",
            "params": {"scenario_id": scenario_id, "name": name},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


# ── Anti-drift pin (moves with the allowlist) ────────────────────────────────


def test_scenario_commit_is_in_both_action_sets():
    assert "scenario_commit" in SUPPORTED_ACTIONS
    assert _HANDLED == set(SUPPORTED_ACTIONS)


# ── Propose does not write ───────────────────────────────────────────────────


def test_propose_scenario_commit_writes_nothing(client, db_session):
    headers = _auth_header(client)
    goal_id = _create_goal(client, headers)
    scenario_id = _create_scenario(client, headers, goal_id)

    token = _propose_commit(client, headers, scenario_id)
    assert token

    # No rule, no plan, no event yet — propose only describes the change.
    assert db_session.execute(select(func.count(RuleORM.id))).scalar_one() == 0
    assert (
        db_session.execute(select(func.count(PlanOfRecordORM.id))).scalar_one() == 0
    )
    assert (
        db_session.execute(
            select(func.count(GameEventORM.id)).where(
                GameEventORM.type == "WhatIfCommitted"
            )
        ).scalar_one()
        == 0
    )


# ── Confirm creates rules + plan + one event (+20 XP) ────────────────────────


def test_confirm_scenario_commit_creates_rule_plan_and_event(client, db_session):
    headers = _auth_header(client)
    goal_id = _create_goal(client, headers)
    scenario_id = _create_scenario(client, headers, goal_id, monthly=200.00)

    token = _propose_commit(client, headers, scenario_id, name="Aggressive")
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": token},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "confirmed"

    db_session.expire_all()

    # Exactly one standing allocate rule, targeting the goal, fixed-dollar.
    rule = db_session.execute(select(RuleORM)).scalar_one()
    assert rule.action_type == "allocate"
    assert rule.target_kind == "goal"
    assert rule.target_id == goal_id
    assert rule.enabled == 1
    assert '"amount": 200.0' in rule.action_params
    assert '"value": "income"' in rule.conditions

    # Exactly one PlanOfRecord, bound to the scenario, carrying the rule id + a
    # snapshot to drift-check against later.
    plan = db_session.execute(select(PlanOfRecordORM)).scalar_one()
    assert plan.scenario_id == scenario_id
    assert str(rule.id) in plan.rule_ids_json
    assert plan.baseline_snapshot_json  # non-empty evaluate() snapshot
    assert plan.status == "active"

    # Exactly one WhatIfCommitted event, keyed on the plan id, carrying the
    # rule/plan ids it minted.
    events = (
        db_session.execute(
            select(GameEventORM).where(GameEventORM.type == "WhatIfCommitted")
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].idempotency_key == f"scenario_commit:{plan.id}"

    # WhatIfCommitted is +20 XP.
    assert player_xp(db_session)["xp"] == 20


# ── Replay safety: same token → 409, no duplicates ───────────────────────────


def test_replayed_confirm_token_does_not_duplicate(client, db_session):
    headers = _auth_header(client)
    goal_id = _create_goal(client, headers)
    scenario_id = _create_scenario(client, headers, goal_id)

    token = _propose_commit(client, headers, scenario_id)

    first = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": token},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    # Replaying the SAME token is rejected by the single-use jti guard.
    second = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": token},
        headers=headers,
    )
    assert second.status_code == 409

    db_session.expire_all()
    # Nothing doubled: one rule, one plan, one event.
    assert db_session.execute(select(func.count(RuleORM.id))).scalar_one() == 1
    assert (
        db_session.execute(select(func.count(PlanOfRecordORM.id))).scalar_one() == 1
    )
    assert (
        db_session.execute(
            select(func.count(GameEventORM.id)).where(
                GameEventORM.type == "WhatIfCommitted"
            )
        ).scalar_one()
        == 1
    )
