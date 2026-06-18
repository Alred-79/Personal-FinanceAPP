"""Confirm-time agent-cache invalidation gating (review fix #4).

Only a memory-mutating confirm (recategorize) should evict the cached executor
and lose the conversation buffer. Confirming a routine write (add_transaction,
add_goal, create_rule) must PRESERVE the cached agent so the user keeps their
chat context. We assert on the singleton's ``agents`` cache directly.
"""

from sqlalchemy import select

from server.src.routers.assistant import assistant_service
from server.src.db.models import Account as AccountORM


def _auth_header(client, username="invuser", email="inv@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Inv User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}, resp.json()


def _uid(db_session, username="invuser"):
    from server.src.db.models import User as UserORM

    return db_session.execute(
        select(UserORM.id).where(UserORM.username == username)
    ).scalar_one()


def _seed_agent(user_id):
    """Put a sentinel in the executor cache so we can see if confirm evicts it."""
    sentinel = object()
    assistant_service.agents[user_id] = sentinel  # type: ignore[assignment]
    return sentinel


def _make_account(client, headers):
    client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": 1000.0},
        headers=headers,
    )
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


def test_add_transaction_confirm_preserves_agent(client, db_session):
    headers, _ = _auth_header(client)
    uid = _uid(db_session)
    acct = _make_account(client, headers)
    sentinel = _seed_agent(uid)

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct,
                "title": "Coffee",
                "amount": 5.0,
                "date": "2026-05-01",
                "category": "Food and Drink",
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
    # The cached agent (and its conversation buffer) survives a non-memory write.
    assert assistant_service.agents.get(uid) is sentinel
    assistant_service.agents.pop(uid, None)  # cleanup the singleton


def test_recategorize_confirm_evicts_agent(client, db_session):
    headers, _ = _auth_header(client, username="invuser2", email="inv2@example.com")
    uid = _uid(db_session, username="invuser2")
    acct = _make_account(client, headers)
    client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": "Trader Joes",
            "amount": 42.0,
            "date": "2026-05-01",
            "category": "Other",
        },
        headers=headers,
    )
    tx_id = client.get("/api/expenses/", headers=headers).json()[-1]["id"]
    sentinel = _seed_agent(uid)

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "recategorize_transaction",
            "params": {"transaction_id": tx_id, "category": "Food", "type": "expense"},
        },
        headers=headers,
    ).json()
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    # A memory-mutating confirm DOES evict, so the next turn rebuilds the prompt.
    assert assistant_service.agents.get(uid) is not sentinel
    assistant_service.agents.pop(uid, None)


# ── W1: mode-complete invalidation + cross-mode continuity ──────────────────
# The router keys executors by ``(user_id, mode_signature)``; invalidation must
# clear EVERY mode for a user, and a shared per-user memory must survive a mode
# switch so a read→money conversation keeps continuity. These exercise the
# AgentConversationCache seam directly (pure of network).


def test_invalidate_clears_all_mode_executors():
    cache = assistant_service.agents
    uid = 90001
    # Seed sentinels under several (user, mode) keys plus the bare key, and a
    # decoy under a different user that must be left untouched.
    a = object()
    b = object()
    c = object()
    decoy = object()
    cache[(uid, "read+money")] = a
    cache[(uid, "read+money+web")] = b
    cache[uid] = c
    cache[(90002, "read+money")] = decoy
    try:
        assistant_service.invalidate_agent(uid)
        # Every (uid, *) key and the bare uid key are gone.
        assert cache.get((uid, "read+money")) is None
        assert cache.get((uid, "read+money+web")) is None
        assert cache.get(uid) is None
        # A different user's executor is untouched.
        assert cache.get((90002, "read+money")) is decoy
    finally:
        cache.pop((90002, "read+money"), None)


def test_shared_memory_preserves_continuity_across_modes():
    """A read turn then a money turn share ONE memory instance, so history from
    the read turn is visible to the money-mode executor (no continuity break)."""
    from langchain_classic.memory import ConversationBufferWindowMemory

    cache = assistant_service.agents
    uid = 90010
    try:
        built = []

        def factory():
            m = ConversationBufferWindowMemory(
                memory_key="chat_history", return_messages=True, k=4
            )
            built.append(m)
            return m

        # First (read) turn builds the shared memory and records a message.
        mem_read = cache.get_or_create_memory(uid, factory)
        mem_read.chat_memory.add_user_message("how much did I spend on coffee")
        # Second (money) turn — a DIFFERENT mode — must get the SAME instance.
        mem_money = cache.get_or_create_memory(uid, factory)
        assert mem_money is mem_read
        assert len(built) == 1  # factory ran exactly once
        # The read turn's history is visible in the money-mode memory.
        assert any(
            "coffee" in getattr(m, "content", "")
            for m in mem_money.chat_memory.messages
        )
    finally:
        cache._memories.pop(uid, None)


def test_invalidate_preserves_shared_memory():
    """Invalidation drops executors (to rebuild the prompt) but keeps the shared
    conversation buffer — the W1 continuity guarantee."""
    from langchain_classic.memory import ConversationBufferWindowMemory

    cache = assistant_service.agents
    uid = 90020
    try:
        mem = cache.get_or_create_memory(
            uid,
            lambda: ConversationBufferWindowMemory(
                memory_key="chat_history", return_messages=True, k=4
            ),
        )
        mem.chat_memory.add_user_message("remember this")
        cache[(uid, "read+money")] = object()
        assistant_service.invalidate_agent(uid)
        # Executor gone, memory (and its buffer) survives.
        assert cache.get((uid, "read+money")) is None
        survived = cache.get_memory(uid)
        assert survived is mem
        assert any(
            "remember this" in getattr(m, "content", "")
            for m in survived.chat_memory.messages
        )
    finally:
        cache._memories.pop(uid, None)
