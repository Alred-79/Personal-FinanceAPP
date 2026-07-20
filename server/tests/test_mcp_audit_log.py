"""Agent Vault — the persisted MCP audit trail (mcp_audit_log).

Covers: audit.record persists a row (hash only, never raw params); the
GET /mcp-keys/audit/ endpoint lists it; rows are owner-scoped; a resolvable
denial is stored as deny:<reason>; an anonymous (user_id=None) failure writes
nothing and never raises.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from server.src.db.models import User as UserORM


@pytest.fixture(autouse=True)
def _redirect_sessionlocal(_engine, monkeypatch):
    """audit.persist opens its OWN SessionLocal (the vault read session rolls
    back). Point that at the per-test engine so the write and the endpoint read
    share one DB (in the default SQLite path they're otherwise separate)."""
    import server.src.db.session as dbsession

    monkeypatch.setattr(
        dbsession,
        "SessionLocal",
        sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        ),
    )
    yield


def _auth(client, username="agentuser", email="agent@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Agent User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _uid(db, username):
    return db.execute(
        select(UserORM).where(UserORM.username == username)
    ).scalar_one().id


def test_record_persists_and_endpoint_lists(client, db_session):
    from server.src.mcp import audit

    headers = _auth(client)
    uid = _uid(db_session, "agentuser")
    audit.record(
        user_id=uid,
        key_id=7,
        resource="tx_by_date",
        params={"start": "2026-01-01", "end": "2026-01-31"},
        decision="allow",
        latency_ms=12.5,
    )

    rows = client.get("/api/mcp-keys/audit/", headers=headers).json()
    assert len(rows) == 1
    r = rows[0]
    assert r["resource"] == "tx_by_date"
    assert r["decision"] == "allow"
    assert r["key_id"] == 7
    assert r["latency_ms"] == 12.5
    # Privacy: a non-empty hash that does NOT leak the raw parameter values.
    assert r["params_hash"]
    assert "2026-01-01" not in r["params_hash"]


def test_audit_owner_scoped(client, db_session):
    from server.src.mcp import audit

    h1 = _auth(client, "agentuser", "agent@example.com")
    h2 = _auth(client, "other", "other@example.com")
    uid1 = _uid(db_session, "agentuser")
    audit.record(user_id=uid1, key_id=1, resource="accounts", decision="allow")

    assert client.get("/api/mcp-keys/audit/", headers=h2).json() == []
    assert len(client.get("/api/mcp-keys/audit/", headers=h1).json()) == 1


def test_resolvable_denial_recorded(client, db_session):
    from server.src.mcp import audit

    headers = _auth(client)
    uid = _uid(db_session, "agentuser")
    audit.record_failure(reason="rate_limited", key_id=3, user_id=uid)

    rows = client.get("/api/mcp-keys/audit/", headers=headers).json()
    assert len(rows) == 1
    assert rows[0]["resource"] == "auth"
    assert rows[0]["decision"] == "deny:rate_limited"


def test_anonymous_failure_writes_nothing(client):
    from server.src.mcp import audit

    headers = _auth(client)
    # An unknown-key flood has no user_id — must not write (and must not raise).
    audit.record_failure(reason="unknown_key", key_id=None, user_id=None)
    assert client.get("/api/mcp-keys/audit/", headers=headers).json() == []


def test_write_failure_is_logged_not_silently_swallowed(caplog):
    """A dropped audit row must leave a trace.

    ``persist`` deliberately never raises — auditing must not break a read. But
    swallowing the failure with a bare ``pass`` means the owner's security record
    can empty itself with no signal anywhere (exactly how the RLS tenant-binding
    bug hid: see test_mcp_audit_rls_postgres.py). Never raising and never
    reporting are different promises; we keep the first, not the second.

    Forces a real failure with an unknown ``user_id`` (FK violation) rather than
    a mock, so the swallow path is exercised as it would actually be hit.
    """
    from server.src.services.mcp_audit_store import persist

    with caplog.at_level(logging.WARNING):
        persist(
            user_id=999_999,  # no such user → FK violation on INSERT
            key_id=1,
            resource="read:accounts",
            decision="allow",
        )

    assert any(
        "audit" in record.getMessage().lower() for record in caplog.records
    ), "a discarded audit row must be reported, not silently dropped"
