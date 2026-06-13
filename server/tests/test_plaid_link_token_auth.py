"""Step 03 (C3): the Plaid link-token endpoint must require auth and derive the
Plaid ``client_user_id`` from the session — never from a caller-supplied param.

Before this step, ``GET /plaid/link-token/?user_id=...`` had NO auth dependency
and minted a real Plaid Link token for an arbitrary id, so anyone on the network
could burn the app's Plaid quota / attach a Link session to a chosen id.
"""

from unittest.mock import MagicMock, patch

from sqlalchemy import select

import server.src.routers.plaid as plaid_router
from server.src.db.models import User as UserORM


def _signup(client, username="linker", email="linker@x.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Link Tester",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    # Use the Bearer header as the sole credential.
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _user_id(db_session, username="linker"):
    """Resolve the signed-up user's numeric id from the shared test engine."""
    user = db_session.execute(
        select(UserORM).where(UserORM.username == username)
    ).scalar_one()
    return int(user.id)


def test_link_token_requires_auth(client):
    """Unauthenticated GET → 401, and the old ``?user_id=`` form is rejected the
    same way (FastAPI 401s on the missing auth dependency before reading params,
    so no Plaid call is ever made)."""
    mock_cls = MagicMock()
    with patch.object(plaid_router, "PlaidClient", mock_cls):
        no_auth = client.get("/api/plaid/link-token/")
        old_form = client.get("/api/plaid/link-token/?user_id=999")

    assert no_auth.status_code == 401, no_auth.text
    assert old_form.status_code == 401, old_form.text
    # The Plaid client was never even constructed — auth rejected first.
    mock_cls.assert_not_called()


def test_link_token_uses_session_user(client, db_session):
    """An authed GET returns a token, and ``create_link_token`` is called with
    ``str(current_user.id)`` derived from the session — NOT any param."""
    headers = _signup(client)
    user_id = _user_id(db_session)

    mock_instance = MagicMock()
    mock_instance.create_link_token.return_value = "link-sandbox-abc123"
    mock_cls = MagicMock(return_value=mock_instance)

    with patch.object(plaid_router, "PlaidClient", mock_cls):
        # Even if a caller smuggles a different user_id, it must be ignored.
        resp = client.get(
            "/api/plaid/link-token/?user_id=999999", headers=headers
        )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"link_token": "link-sandbox-abc123"}
    mock_instance.create_link_token.assert_called_once_with(str(user_id))
