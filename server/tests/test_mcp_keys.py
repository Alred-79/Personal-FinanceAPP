"""Tests for the MCP API-key credential store.

Uses the ``conftest`` in-memory engine, mirroring ``test_auth.py``.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from server.src.db.models import MCPKey, User as UserORM
from server.src.mcp.principal import Principal
from server.src.services.mcp_key_service import MCPKeyService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, username="alice", email="alice@example.com") -> int:
    """Insert a minimal user and return the ``user_id``."""
    user = UserORM(
        username=username,
        full_name=f"{username.title()} Example",
        email=email,
        hashed_password="fakehash",
    )
    db.add(user)
    db.flush()
    return user.id


# ---------------------------------------------------------------------------
# 1. create returns a raw key; stored row has key_hash != raw
# ---------------------------------------------------------------------------

def test_create_returns_raw_key_and_row(db_session):
    uid = _make_user(db_session)
    raw, row = MCPKeyService.create(
        db_session, uid, "My key", ["transactions:read"]
    )

    # Raw key starts with the expected prefix and has decent length.
    assert raw.startswith("bdgt_live_")
    assert len(raw) > 30

    # The stored hash is NOT the raw key.
    assert row.key_hash != raw
    assert row.key_hash  # not empty

    # The prefix matches the first 12 chars of the raw key.
    assert row.key_prefix == raw[:12]

    # Legacy scopes are normalized to the modern read:* form on storage.
    assert row.scopes == "read:transactions"

    # No raw key value anywhere in the row's columns.
    for col in ("key_hash", "key_prefix", "name", "scopes"):
        assert getattr(row, col) != raw


def test_create_mixed_scopes_keeps_only_usable(db_session):
    """A mix of read + write legacy scopes stores only the usable read:* forms."""
    uid = _make_user(db_session)
    _, row = MCPKeyService.create(
        db_session, uid, "mixed",
        ["transactions:read", "transactions:write", "read:goals"],
    )
    assert set(row.scopes.split(",")) == {"read:transactions", "read:goals"}


def test_create_only_unusable_scopes_rejected(db_session):
    """Scopes that grant no MCP read tool (write/chat) leave nothing usable."""
    uid = _make_user(db_session)
    with pytest.raises(ValueError):
        MCPKeyService.create(
            db_session, uid, "write-only", ["transactions:write", "assistant:chat"]
        )


# ---------------------------------------------------------------------------
# 2. resolve round-trips to the right Principal
# ---------------------------------------------------------------------------

def test_resolve_roundtrips(db_session):
    uid = _make_user(db_session)
    raw, row = MCPKeyService.create(
        db_session, uid, "round-trip", ["budgets:read", "budgets:write"]
    )

    principal = MCPKeyService.resolve(db_session, raw)
    assert principal is not None
    assert isinstance(principal, Principal)
    assert principal.user_id == uid
    assert principal.key_id == row.id
    # budgets:read → read:budgets; budgets:write grants no read tool and is dropped.
    assert principal.scopes == frozenset(["read:budgets"])


# ---------------------------------------------------------------------------
# 3. Revoked key → resolve is None
# ---------------------------------------------------------------------------

def test_revoked_key_resolves_to_none(db_session):
    uid = _make_user(db_session)
    raw, row = MCPKeyService.create(
        db_session, uid, "will-revoke", ["transactions:read"]
    )
    MCPKeyService.revoke(db_session, uid, row.id)

    assert MCPKeyService.resolve(db_session, raw) is None


# ---------------------------------------------------------------------------
# 4. Expired key → resolve is None
# ---------------------------------------------------------------------------

def test_expired_key_resolves_to_none(db_session):
    uid = _make_user(db_session)
    raw, row = MCPKeyService.create(
        db_session, uid, "expired", ["transactions:read"], ttl_days=1
    )
    # Force expires_at into the past.
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.flush()

    assert MCPKeyService.resolve(db_session, raw) is None


# ---------------------------------------------------------------------------
# 5. Wrong / garbage key → resolve is None (no raise)
# ---------------------------------------------------------------------------

def test_garbage_key_resolves_to_none(db_session):
    _make_user(db_session)
    assert MCPKeyService.resolve(db_session, "bdgt_live_totallygarbage") is None
    assert MCPKeyService.resolve(db_session, "") is None
    assert MCPKeyService.resolve(db_session, "random-string-1234") is None


# ---------------------------------------------------------------------------
# 6. Scope validation
# ---------------------------------------------------------------------------

def test_unknown_scope_rejected(db_session):
    uid = _make_user(db_session)
    with pytest.raises(ValueError, match="Unknown scope"):
        MCPKeyService.create(db_session, uid, "bad", ["nuclear:launch"])


def test_empty_scopes_rejected(db_session):
    uid = _make_user(db_session)
    with pytest.raises(ValueError, match="At least one scope"):
        MCPKeyService.create(db_session, uid, "empty", [])


# ---------------------------------------------------------------------------
# 7. list returns metadata with prefixes and NO hash/raw
# ---------------------------------------------------------------------------

def test_list_returns_metadata_without_secrets(db_session):
    uid = _make_user(db_session)
    raw1, _ = MCPKeyService.create(
        db_session, uid, "key-one", ["transactions:read"]
    )
    raw2, _ = MCPKeyService.create(
        db_session, uid, "key-two", ["budgets:read"]
    )

    keys = MCPKeyService.list_keys(db_session, uid)
    assert len(keys) == 2

    for k in keys:
        # Must have metadata.
        assert "id" in k
        assert "name" in k
        assert "key_prefix" in k
        assert "scopes" in k
        assert "created_at" in k
        assert "expires_at" in k
        assert "revoked" in k

        # Must NOT have secrets.
        assert "key_hash" not in k
        assert "raw" not in k

        # Prefix should match the first 12 chars of a raw key.
        assert k["key_prefix"].startswith("bdgt_live_")


# ---------------------------------------------------------------------------
# 8. Cross-user revoke denied; double revoke idempotent
# ---------------------------------------------------------------------------

def test_cross_user_revoke_denied(db_session):
    uid_a = _make_user(db_session, "userA", "a@example.com")
    uid_b = _make_user(db_session, "userB", "b@example.com")

    _, row_a = MCPKeyService.create(
        db_session, uid_a, "a-key", ["transactions:read"]
    )

    # User B cannot revoke user A's key.
    assert MCPKeyService.revoke(db_session, uid_b, row_a.id) is False

    # Key is still valid.
    assert not db_session.get(MCPKey, row_a.id).revoked


def test_double_revoke_idempotent(db_session):
    uid = _make_user(db_session)
    raw, row = MCPKeyService.create(
        db_session, uid, "double", ["transactions:read"]
    )

    assert MCPKeyService.revoke(db_session, uid, row.id) is True
    assert MCPKeyService.revoke(db_session, uid, row.id) is True  # no error

    # Still revoked, revoked_at is set.
    refreshed = db_session.get(MCPKey, row.id)
    assert refreshed.revoked == 1
    assert refreshed.revoked_at is not None


# ---------------------------------------------------------------------------
# 9. Cascade: deleting the user removes their mcp_keys rows
# ---------------------------------------------------------------------------

def test_cascade_delete_user_removes_keys(db_session):
    uid = _make_user(db_session)
    MCPKeyService.create(db_session, uid, "k1", ["transactions:read"])
    MCPKeyService.create(db_session, uid, "k2", ["budgets:read"])
    db_session.flush()

    assert db_session.execute(
        select(MCPKey).where(MCPKey.user_id == uid)
    ).scalars().all()

    user = db_session.get(UserORM, uid)
    db_session.delete(user)
    db_session.flush()

    remaining = db_session.execute(
        select(MCPKey).where(MCPKey.user_id == uid)
    ).scalars().all()
    assert remaining == []


# ---------------------------------------------------------------------------
# Extra: last_used_at throttling
# ---------------------------------------------------------------------------

def test_last_used_at_updated_on_first_resolve(db_session):
    uid = _make_user(db_session)
    raw, row = MCPKeyService.create(
        db_session, uid, "usage", ["transactions:read"]
    )
    assert row.last_used_at is None

    MCPKeyService.resolve(db_session, raw)
    db_session.expire(row)
    assert row.last_used_at is not None


# ---------------------------------------------------------------------------
# Principal is frozen
# ---------------------------------------------------------------------------

def test_principal_is_frozen():
    p = Principal(user_id=1, key_id=2, scopes=frozenset(["a"]))
    with pytest.raises(AttributeError):
        p.user_id = 99  # type: ignore[misc]
