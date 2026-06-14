"""Pillar 2.0 — the generic tool→frame registry over the chat stream.

The gap this closes: before 2.0 only ``what_if`` surfaced a structured card.
Every other write tool (``create_rule``, ``add_transaction``, ``add_goal``,
``recategorize_transaction``) returned its ``needs_confirmation`` JSON into model
context with NO ``on_tool_end`` handler and NO client renderer — so the signed
confirm token had no clickable Approve path in chat (its API-only tests POST
``/actions/propose`` directly, bypassing the stream).

These tests drive a write tool through the REAL ``AssistantService.chat``
generator (the executor's ``astream_events`` is faked to emit one ``on_tool_end``
event carrying the tool's real envelope) and assert a ``proposal`` SSE frame is
emitted with a DECODABLE ``confirm_token`` — the chat-path coverage the
propose/confirm tests don't provide. Mirrors ``test_assistant_whatif.py``'s
``_proposal_frame`` assertions, but end to end through ``chat``.
"""

import json

import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import sessionmaker

import server.src.services.assistant_service as svc_mod
from server.src.db.models import Account as AccountORM, User as UserORM
from server.src.models import UserInDB
from server.src.services.assistant_service import (
    ActionService,
    AssistantService,
    _propose_action,
    _PROPOSAL_FRAME_TOOLS,
    _propose_rule,
)


def _bind_session(monkeypatch, _engine):
    TestSession = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    monkeypatch.setattr(svc_mod, "SessionLocal", TestSession)
    return TestSession


def _user(db_session, with_goal=False):
    user = UserORM(username="fr", full_name="FR", email="fr@x.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        AccountORM(name="Checking", type="checking", balance=200_000, user_id=user.id)
    )
    goal_id = None
    if with_goal:
        from server.src.db.models import Goal as GoalORM

        goal = GoalORM(
            name="House", amount=1_000_000, date="2028-01-01", user_id=user.id, progress=0
        )
        db_session.add(goal)
        db_session.flush()
        goal_id = goal.id
    db_session.commit()
    return user, goal_id


def _as_userindb(user) -> UserInDB:
    return UserInDB(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        disabled=False,
        hashed_password="x",
    )


async def _drive_chat_with_tool_event(monkeypatch, user, tool_name, tool_output):
    """Run the real ``chat`` generator with a faked executor that emits exactly
    one ``on_tool_end`` for *tool_name* carrying *tool_output*, then a done.

    Returns the list of SSE frame strings the generator yielded.
    """
    service = AssistantService.__new__(AssistantService)  # skip ChatGroq init
    # Minimal attributes ``chat`` touches before streaming.
    from cachetools import TTLCache

    service.agents = TTLCache(maxsize=8, ttl=1800)
    service.actions = {tool_name: ""}
    service.preprocessors = {}

    executor = MagicMock()

    async def _events(*args, **kwargs):
        # The model "calls" the write tool, which returns the proposal envelope.
        yield {"event": "on_chat_model_start", "name": "ChatGroq", "data": {}}
        yield {
            "event": "on_tool_end",
            "name": tool_name,
            "data": {"output": tool_output},
        }

    executor.astream_events = _events
    service.agents[user.id] = executor

    frames: list[str] = []
    async for frame in service.chat(_as_userindb(user), "do the thing"):
        frames.append(frame)
    return frames


def _find_proposal(frames):
    for f in frames:
        if f.startswith("event: proposal\n"):
            return json.loads(f.split("data: ", 1)[1])
    return None


@pytest.mark.asyncio
async def test_create_rule_emits_proposal_frame_with_decodable_token(
    monkeypatch, db_session, _engine
):
    _bind_session(monkeypatch, _engine)
    user, goal_id = _user(db_session, with_goal=True)

    # The real tool body resolves the goal name → target_id and mints the token.
    envelope = _propose_rule(
        user.id,
        action_type="allocate",
        name="Payday savings",
        conditions=[{"field": "type", "op": "eq", "value": "income"}],
        amount=50.0,
        goal_name="House",
    )
    # Sanity: it produced a proposal envelope (not a guidance string).
    assert json.loads(envelope)["kind"] == "proposal"

    frames = await _drive_chat_with_tool_event(
        monkeypatch, user, "create_rule", envelope
    )
    body = _find_proposal(frames)
    assert body is not None, f"no proposal frame in {frames}"
    assert body["action"] == "create_rule"
    # The token decodes and is a real create_rule confirm token for this goal.
    claims = ActionService.decode_token(body["confirm_token"])
    assert claims["action"] == "create_rule"
    assert claims["params"]["target_id"] == goal_id
    # A plain rule proposal carries no what-if diff.
    assert "diff" not in body


@pytest.mark.asyncio
async def test_add_transaction_emits_proposal_frame(monkeypatch, db_session, _engine):
    """A second write tool proves the registry is generic, not what_if/rule-only."""
    _bind_session(monkeypatch, _engine)
    user, _ = _user(db_session)
    # Resolve the account so add_transaction validates.
    from sqlalchemy import select
    from server.src.db.models import Account as AccountORM2

    acct_id = db_session.execute(
        select(AccountORM2.id).where(AccountORM2.user_id == user.id)
    ).scalar_one()

    envelope = _propose_action(
        "add_transaction",
        user.id,
        {
            "type": "expense",
            "account_id": acct_id,
            "title": "Coffee",
            "amount": 4.5,
            "date": "2026-06-01",
            "category": "Food",
        },
    )
    frames = await _drive_chat_with_tool_event(
        monkeypatch, user, "add_transaction", envelope
    )
    body = _find_proposal(frames)
    assert body is not None
    assert body["action"] == "add_transaction"
    assert ActionService.decode_token(body["confirm_token"])["action"] == "add_transaction"


def test_all_write_tools_are_registered_for_frames():
    """Every propose→confirm write tool surfaces a ConfirmCard in chat (2.0).

    A new write tool that forgets to register would silently regress to the
    pre-2.0 dead-end (token in model context, no Approve button).
    """
    assert _PROPOSAL_FRAME_TOOLS == {
        "what_if",
        "create_rule",
        "add_transaction",
        "add_goal",
        "recategorize_transaction",
    }
