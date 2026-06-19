"""L1 — Plaid inbound webhooks: ES256 verification, dispatch, endpoint, wiring.

Runs on SQLite (Base.metadata.create_all gives tokens.item_id; RLS no-ops). The
Plaid network is mocked: test JWTs are signed with a locally-generated EC P-256
key whose public JWK the verifier's key_fetcher returns.
"""

from __future__ import annotations

import hashlib
import json
import time
from unittest.mock import MagicMock, patch

import jwt
import jwt.algorithms  # noqa: F401 — ensure ECAlgorithm.to_jwk is available
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from server.src.databridge.plaid_client import SyncResult
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Notification as NotificationORM,
    Token as TokenORM,
    User as UserORM,
)
from server.src.services.plaid_webhook import (
    PlaidWebhookVerifier,
    WebhookVerificationError,
    dispatch,
)


@pytest.fixture(autouse=True)
def _clear_key_cache():
    """The verification-key cache is module-level; each test uses a FRESH key under
    the same 'testkid', so a stale cached key would fail verification. Clear it."""
    import server.src.services.plaid_webhook as wh

    wh._KEY_CACHE.clear()
    yield
    wh._KEY_CACHE.clear()


@pytest.fixture
def signer():
    """An EC P-256 keypair + helpers to mint signed webhook JWTs and a verifier
    whose key_fetcher returns the matching public JWK."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pub_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(priv.public_key()))
    pub_jwk["kid"] = "testkid"
    pub_jwk["expired_at"] = None

    calls = {"n": 0}

    def fetch(kid):
        calls["n"] += 1
        if kid != "testkid":
            raise RuntimeError("unknown kid")
        return dict(pub_jwk)

    def sign(body: bytes, *, iat=None, kid="testkid"):
        claims = {
            "iat": int(time.time()) if iat is None else iat,
            "request_body_sha256": hashlib.sha256(body).hexdigest(),
        }
        return jwt.encode(claims, priv, algorithm="ES256", headers={"kid": kid})

    return type(
        "Signer", (), {"priv": priv, "fetch": staticmethod(fetch),
                       "sign": staticmethod(sign), "calls": calls}
    )


def _body(**kw) -> bytes:
    return json.dumps(kw).encode()


# ── verification ─────────────────────────────────────────────────────────────

def test_valid_webhook_verifies(signer):
    v = PlaidWebhookVerifier(key_fetcher=signer.fetch)
    b = _body(webhook_type="TRANSACTIONS", webhook_code="SYNC_UPDATES_AVAILABLE", item_id="i1")
    out = v.verify(b, signer.sign(b))
    assert out["item_id"] == "i1"


def test_missing_header_rejected(signer):
    v = PlaidWebhookVerifier(key_fetcher=signer.fetch)
    with pytest.raises(WebhookVerificationError):
        v.verify(_body(item_id="i1"), None)


def test_tampered_signature_rejected(signer):
    v = PlaidWebhookVerifier(key_fetcher=signer.fetch)
    b = _body(item_id="i1")
    tok = signer.sign(b)
    with pytest.raises(WebhookVerificationError):
        v.verify(b, tok[:-4] + "AAAA")


def test_body_hash_mismatch_rejected(signer):
    """A JWT signed over body A can't validate body B (the binding property)."""
    v = PlaidWebhookVerifier(key_fetcher=signer.fetch)
    tok = signer.sign(_body(item_id="A"))
    with pytest.raises(WebhookVerificationError):
        v.verify(_body(item_id="B"), tok)


def test_stale_iat_rejected(signer):
    v = PlaidWebhookVerifier(key_fetcher=signer.fetch)
    b = _body(item_id="i1")
    with pytest.raises(WebhookVerificationError):
        v.verify(b, signer.sign(b, iat=int(time.time()) - 1000))


def test_wrong_alg_rejected(signer):
    """An HS256 token (alg substitution attempt) is rejected before decode."""
    v = PlaidWebhookVerifier(key_fetcher=signer.fetch)
    b = _body(item_id="i1")
    hs = jwt.encode(
        {"iat": int(time.time()), "request_body_sha256": hashlib.sha256(b).hexdigest()},
        "secret", algorithm="HS256", headers={"kid": "testkid"},
    )
    with pytest.raises(WebhookVerificationError):
        v.verify(b, hs)


def test_key_is_cached_after_first_fetch(signer):
    """The verification key is fetched once per kid, then cached."""
    import server.src.services.plaid_webhook as wh

    wh._KEY_CACHE.clear()
    v = PlaidWebhookVerifier(key_fetcher=signer.fetch)
    b = _body(item_id="i1")
    v.verify(b, signer.sign(b))
    v.verify(b, signer.sign(b))
    assert signer.calls["n"] == 1  # second verify hit the cache


# ── dispatch ─────────────────────────────────────────────────────────────────

def _seed_user_token(db, *, item_id="item-1"):
    u = UserORM(username="wh", full_name="W", email="w@x.com", hashed_password="x")
    db.add(u)
    db.flush()
    acct = AccountORM(
        name="Checking", type="depository", balance=0,
        plaid_account_id="acct-A", user_id=u.id,
    )
    tok = TokenORM(user_id=u.id, name="Bank", key="plain-tok", item_id=item_id)
    db.add_all([acct, tok])
    db.flush()
    return u, tok, acct


@patch("server.src.services.plaid_service.PlaidClient")
def test_dispatch_sync_updates_available_runs_sync(MockPC, db_session):
    from .conftest import wire_plaid_pages

    u, tok, acct = _seed_user_token(db_session)
    mock = MagicMock()
    MockPC.return_value = wire_plaid_pages(mock)
    mock.get_balance.return_value = []
    mock.sync_transactions.return_value = SyncResult(
        added=[{
            "transaction_id": "w1", "name": "Lunch", "amount": 9.0,
            "date": "2026-06-10", "account_id": "acct-A",
            "category": ["Food"], "personal_finance_category": None,
        }],
        modified=[], removed=[], next_cursor="c1",
    )
    dispatch(db_session, {
        "webhook_type": "TRANSACTIONS", "webhook_code": "SYNC_UPDATES_AVAILABLE",
        "item_id": tok.item_id,
    })
    rows = db_session.execute(select(ExpenseORM)).scalars().all()
    assert [r.plaid_transaction_id for r in rows] == ["w1"]


def test_dispatch_item_login_required_makes_relink(db_session):
    u, tok, acct = _seed_user_token(db_session)
    dispatch(db_session, {
        "webhook_type": "ITEM", "webhook_code": "ITEM_LOGIN_REQUIRED",
        "item_id": tok.item_id,
    })
    notes = db_session.execute(
        select(NotificationORM).where(NotificationORM.type == "plaid_relink")
    ).scalars().all()
    assert len(notes) == 1 and notes[0].ref == f"plaid_relink:{tok.id}"


def test_dispatch_pending_expiration_makes_relink(db_session):
    u, tok, acct = _seed_user_token(db_session)
    dispatch(db_session, {
        "webhook_type": "ITEM", "webhook_code": "PENDING_EXPIRATION",
        "item_id": tok.item_id,
    })
    notes = db_session.execute(
        select(NotificationORM).where(NotificationORM.type == "plaid_relink")
    ).scalars().all()
    assert len(notes) == 1


def test_dispatch_item_error_nonrelink_code_is_noop(db_session):
    u, tok, acct = _seed_user_token(db_session)
    dispatch(db_session, {
        "webhook_type": "ITEM", "webhook_code": "ERROR",
        "item_id": tok.item_id, "error": {"error_code": "INTERNAL_SERVER_ERROR"},
    })
    notes = db_session.execute(select(NotificationORM)).scalars().all()
    assert notes == []


def test_dispatch_unknown_item_is_noop(db_session):
    _seed_user_token(db_session, item_id="item-known")
    # No exception, no rows for an item we don't have.
    dispatch(db_session, {
        "webhook_type": "TRANSACTIONS", "webhook_code": "SYNC_UPDATES_AVAILABLE",
        "item_id": "item-UNKNOWN",
    })
    assert db_session.execute(select(ExpenseORM)).scalars().all() == []


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_endpoint_401_on_bad_signature(client, db_session):
    resp = client.post("/api/plaid/webhook", content=b"{}", headers={})
    assert resp.status_code == 401


def test_endpoint_200_and_dispatches_on_valid(client, db_session, signer, monkeypatch):
    import server.src.routers.plaid_webhook as wh_router

    u, tok, acct = _seed_user_token(db_session, item_id="ep-item")
    db_session.commit()  # the background task uses its own session

    # Use a verifier wired to the test key.
    monkeypatch.setattr(wh_router, "_verifier", PlaidWebhookVerifier(key_fetcher=signer.fetch))
    captured = {}
    monkeypatch.setattr(wh_router, "_process_webhook", lambda payload: captured.update(payload))

    b = _body(webhook_type="ITEM", webhook_code="ITEM_LOGIN_REQUIRED", item_id="ep-item")
    resp = client.post("/api/plaid/webhook", content=b,
                       headers={"Plaid-Verification": signer.sign(b)})
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"
    # The verified payload reached the background processor.
    assert captured.get("item_id") == "ep-item"


def test_endpoint_invalid_sig_does_not_dispatch(client, db_session, signer, monkeypatch):
    import server.src.routers.plaid_webhook as wh_router

    monkeypatch.setattr(wh_router, "_verifier", PlaidWebhookVerifier(key_fetcher=signer.fetch))
    spy = MagicMock()
    monkeypatch.setattr(wh_router, "_process_webhook", spy)
    resp = client.post("/api/plaid/webhook", content=_body(item_id="x"),
                       headers={"Plaid-Verification": "garbage"})
    assert resp.status_code == 401
    spy.assert_not_called()


# ── wiring: exchange stores item_id, link token carries webhook ──────────────

def test_exchange_persists_item_id(client, db_session, monkeypatch):
    from server.src.databridge.plaid_client import ExchangeResult
    import server.src.routers.plaid as plaid_router
    from server.src.services.plaid_service import PlaidService

    headers = _signup(client)

    fake = MagicMock()
    fake.exchange_public_token.return_value = ExchangeResult(
        access_token="access-x", item_id="exch-item-99"
    )
    fake.get_balance.return_value = [_balance_obj("acct-1", "depository")]
    monkeypatch.setattr(plaid_router, "PlaidClient", lambda: fake)
    # The endpoint fires a background initial-sync that opens its OWN session; under
    # the Postgres test StaticPool (one shared connection) that contends with
    # db_session. We only assert the endpoint's synchronous item_id persistence, so
    # no-op the background scheduling. (The sync path itself is covered elsewhere.)
    from fastapi import BackgroundTasks

    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, *a, **k: None)
    monkeypatch.setattr(PlaidService, "sync_token", lambda self, token: {})

    resp = client.post(
        "/api/plaid/exchange-public-token/",
        json={"public_token": "public-x", "name": "MyBank"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tok = db_session.execute(select(TokenORM)).scalars().first()
    assert tok is not None and tok.item_id == "exch-item-99"


def test_create_link_token_includes_webhook_when_set(monkeypatch):
    from server.src.databridge.plaid_client import PlaidClient
    from server.src.settings import settings

    monkeypatch.setattr(settings, "plaid_webhook_url", "https://example.com/api/plaid/webhook")
    captured = {}

    def _create(request, **kw):
        captured["webhook"] = getattr(request, "webhook", None)
        return {"link_token": "lt"}

    pc = PlaidClient()
    monkeypatch.setattr(pc.client, "link_token_create", _create)
    pc.create_link_token("user-1")
    assert captured["webhook"] == "https://example.com/api/plaid/webhook"


def test_create_link_token_omits_webhook_when_unset(monkeypatch):
    from server.src.databridge.plaid_client import PlaidClient
    from server.src.settings import settings

    monkeypatch.setattr(settings, "plaid_webhook_url", None)
    captured = {}

    def _create(request, **kw):
        # An unset webhook attr raises AttributeError on the plaid model.
        try:
            captured["webhook"] = request.webhook
        except AttributeError:
            captured["webhook"] = "ABSENT"
        return {"link_token": "lt"}

    pc = PlaidClient()
    monkeypatch.setattr(pc.client, "link_token_create", _create)
    pc.create_link_token("user-1")
    assert captured["webhook"] == "ABSENT"


# ── helpers ──────────────────────────────────────────────────────────────────

def _signup(client, username="whuser", email="whuser@x.com"):
    resp = client.post("/api/signup/", json={
        "username": username, "email": email,
        "full_name": "WH User", "password": "Test-password1",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _balance_obj(account_id, type_):
    """A stand-in for a Plaid account object with .to_dict()."""
    obj = MagicMock()
    obj.to_dict.return_value = {
        "account_id": account_id, "type": type_, "name": "Checking",
        "balances": {"available": 100.0, "current": 100.0},
    }
    return obj
