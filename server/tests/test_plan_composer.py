from __future__ import annotations

from datetime import date
import random

import pytest
from sqlalchemy import select

from server.src.db.models import Account, Goal, Scenario, User
from server.src.services.plan_composer_service import PlanComposerError, PlanComposerService
from server.src.services.scenario_overlay import GoalMutation, ScenarioOverlay
from server.src.services.scenario_service import ScenarioService
from server.src.settings import Settings, settings


AS_OF = date(2026, 7, 23)


def _owner(db, uid: int = 1, balance: int = 100_000) -> User:
    user = User(
        id=uid,
        username=f"composer-{uid}",
        full_name="Composer Owner",
        email=f"composer-{uid}@example.test",
        hashed_password="unused",
        s2s_horizon="week",
        s2s_include_income=0,
        s2s_include_goals=1,
        s2s_buffer=10_000,
        savings_percent=0,
    )
    db.add(user)
    db.flush()
    db.add(Account(name=f"Checking-{uid}", type="checking", balance=balance, user_id=uid))
    db.flush()
    return user


def _goal(
    db,
    user_id: int,
    gid: int,
    *,
    amount: int = 50_000,
    progress: int = 10_000,
    completed: int = 0,
    deadline: str = "2027-01-01",
) -> Goal:
    row = Goal(
        id=gid,
        name=f"Goal {gid}",
        description="",
        amount=amount,
        progress=progress,
        completed=completed,
        date=deadline,
        user_id=user_id,
    )
    db.add(row)
    db.flush()
    return row


def test_preview_is_cent_exact_absolute_and_never_persists(db_session):
    owner = _owner(db_session)
    goal = _goal(db_session, owner.id, 11)
    result = PlanComposerService(db_session).compose(
        owner.id,
        max_allocation_cents=20_001,
        additional_buffer_cents=10_000,
        goal_ids=[goal.id],
        priority="buffer",
        as_of=AS_OF,
    )
    assert result["persistable"] is False
    assert "overlay" not in str(result).lower()
    assert db_session.execute(select(Scenario)).scalars().all() == []
    for draft in result["drafts"]:
        allocation = draft["allocation"]
        cents = round(allocation["total"] * 100)
        unallocated = round(allocation["unallocated"] * 100)
        assert cents + unallocated == round(result["amount_modeled"] * 100)
        assert round(allocation["buffer_floor"]["proposed"] * 100) == (
            owner.s2s_buffer + round(allocation["buffer_floor"]["delta"] * 100)
        )
        for item in allocation["goals"]:
            assert round(item["proposed_progress"] * 100) == (
                goal.progress + round(item["delta"] * 100)
            )
            assert round(item["proposed_progress"] * 100) <= goal.amount


def test_input_is_capped_by_non_negative_baseline(db_session):
    owner = _owner(db_session, balance=12_345)
    owner.s2s_include_goals = 0
    owner.s2s_buffer = 0
    result = PlanComposerService(db_session).compose(
        owner.id,
        max_allocation_cents=99_999,
        additional_buffer_cents=99_999,
        goal_ids=[],
        as_of=AS_OF,
    )
    assert result["baseline_non_negative_cap"] == 123.45
    assert result["amount_modeled"] == 123.45
    assert result["drafts"][0]["allocation"]["total"] <= 123.45


@pytest.mark.parametrize("kind", ["foreign", "completed", "missing"])
def test_foreign_completed_and_missing_goals_are_rejected(db_session, kind):
    owner = _owner(db_session, 1)
    other = _owner(db_session, 2)
    if kind == "foreign":
        target = _goal(db_session, other.id, 20).id
    elif kind == "completed":
        target = _goal(db_session, owner.id, 21, completed=1).id
    else:
        target = 9999
    with pytest.raises(PlanComposerError):
        PlanComposerService(db_session).compose(
            owner.id,
            max_allocation_cents=100,
            additional_buffer_cents=0,
            goal_ids=[target],
            as_of=AS_OF,
        )


def test_balanced_rounding_remainder_is_deterministic(db_session):
    owner = _owner(db_session)
    owner.s2s_include_goals = 0  # isolate allocation math from S2S goal pacing
    owner.s2s_buffer = 0
    goals = [_goal(db_session, owner.id, gid, progress=0) for gid in (1, 2, 3)]
    service = PlanComposerService(db_session)
    one = service.compose(
        owner.id,
        max_allocation_cents=101,
        additional_buffer_cents=0,
        goal_ids=[goal.id for goal in goals],
        priority="balanced",
        as_of=AS_OF,
    )
    two = service.compose(
        owner.id,
        max_allocation_cents=101,
        additional_buffer_cents=0,
        goal_ids=[goal.id for goal in goals],
        priority="balanced",
        as_of=AS_OF,
    )
    assert one == two
    balanced = next(d for d in one["drafts"] if d["method"] == "balanced")
    deltas = [round(item["delta"] * 100) for item in balanced["allocation"]["goals"]]
    assert deltas == [34, 34, 33]
    assert sum(deltas) == 101


def test_card_evaluation_reproduces_direct_scenario_service(db_session):
    owner = _owner(db_session)
    goal = _goal(db_session, owner.id, 5)
    result = PlanComposerService(db_session).compose(
        owner.id,
        max_allocation_cents=15_000,
        additional_buffer_cents=5_000,
        goal_ids=[goal.id],
        priority="buffer",
        as_of=AS_OF,
    )
    card = result["drafts"][0]
    alloc = card["allocation"]
    goal_delta = round(alloc["goals"][0]["delta"] * 100)
    buffer_delta = round(alloc["buffer_floor"]["delta"] * 100)
    overlay = ScenarioOverlay(
        goal_mutations=(
            GoalMutation(goal_id=goal.id, progress_cents=goal.progress + goal_delta),
        ),
        config_overrides={"s2s_buffer": owner.s2s_buffer + buffer_delta},
    )
    direct = ScenarioService(db_session).evaluate(
        owner.id,
        overlay,
        as_of=AS_OF,
        horizon_days=90,
        rng=random.Random(0),
        name=card["name"],
    )
    assert card["evaluation"] == direct


def test_composer_flag_defaults_off():
    assert Settings.model_fields["plan_composer_enabled"].default is False


def _auth(client):
    response = client.post(
        "/api/signup/",
        json={
            "username": "composer-api",
            "email": "composer-api@example.com",
            "full_name": "Composer API",
            "password": "Test-password1",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_preview_route_ships_dark_and_returns_no_persistence_material(client, monkeypatch):
    headers = _auth(client)
    created = client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": 1000},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    payload = {
        "max_allocation": 100,
        "additional_buffer_floor": 75,
        "goal_ids": [],
        "priority": "balanced",
    }
    monkeypatch.setattr(settings, "plan_composer_enabled", False)
    assert client.post(
        "/api/scenarios/compose-preview/", json=payload, headers=headers
    ).status_code == 404

    monkeypatch.setattr(settings, "plan_composer_enabled", True)
    response = client.post(
        "/api/scenarios/compose-preview/", json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["persistable"] is False
    assert "overlay" not in str(body).lower()
    assert all(
        draft["evaluation"]["scenario"]["scenario_id"] is None
        for draft in body["drafts"]
    )
    assert client.get("/api/scenarios/", headers=headers).json() == []
