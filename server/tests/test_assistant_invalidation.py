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
