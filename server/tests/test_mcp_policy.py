"""Tests for MCP policy, capability tokens, and audit.

Covers:
1. ``require`` allows/denies by scope.
2. ``issue_capability`` → ``verify_capability`` round-trips claims.
3. Escalation blocked.
4. Expired capability → rejected.
5. Tampered / wrong-key → rejected.
6. Type confusion across auth / action / capability tokens.
7. Audit ``record`` emits structured lines with no secrets.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from server.src.mcp.audit import _canonical_params_hash, record
from server.src.mcp.policy import (
    PolicyError,
    _CAPABILITY_TOKEN_TYPE,
    issue_capability,
    require,
    verify_capability,
)
from server.src.mcp.principal import Principal
from server.src.settings import settings

# Shared test fixtures -------------------------------------------------------

_SCOPES = frozenset(["transactions:read", "budgets:read"])
_PRINCIPAL = Principal(user_id=42, key_id=7, scopes=_SCOPES)


# ---------------------------------------------------------------------------
# 1. require: allows when scope present, raises when absent
# ---------------------------------------------------------------------------

def test_require_allows_present_scope():
    """No exception means the scope check passed."""
    require(_PRINCIPAL, "transactions:read")
    require(_PRINCIPAL, "budgets:read")


def test_require_denies_absent_scope():
    with pytest.raises(PolicyError, match="transactions:write"):
        require(_PRINCIPAL, "transactions:write")


def test_require_denies_empty_scopes():
    empty = Principal(user_id=1, key_id=1, scopes=frozenset())
    with pytest.raises(PolicyError):
        require(empty, "anything")


# ---------------------------------------------------------------------------
# 2. issue_capability → verify_capability round-trips
# ---------------------------------------------------------------------------

def test_capability_round_trip():
    token = issue_capability(_PRINCIPAL, ["transactions:read"])
    claims = verify_capability(token)

    assert claims["uid"] == 42
    assert claims["kid"] == 7
    assert claims["scopes"] == ["transactions:read"]
    assert claims["typ"] == _CAPABILITY_TOKEN_TYPE
    assert "jti" in claims
    assert "exp" in claims


def test_capability_round_trip_multiple_scopes():
    token = issue_capability(_PRINCIPAL, ["transactions:read", "budgets:read"])
    claims = verify_capability(token)
    # Scopes are sorted deterministically.
    assert claims["scopes"] == ["budgets:read", "transactions:read"]


# ---------------------------------------------------------------------------
# 3. Escalation blocked
# ---------------------------------------------------------------------------

def test_escalation_blocked():
    with pytest.raises(PolicyError, match="escalation"):
        issue_capability(_PRINCIPAL, ["transactions:write"])


def test_escalation_blocked_partial_overlap():
    """Even if one scope is valid, one invalid scope blocks the whole issue."""
    with pytest.raises(PolicyError, match="escalation"):
        issue_capability(_PRINCIPAL, ["transactions:read", "nuclear:launch"])


def test_empty_scopes_rejected():
    with pytest.raises(PolicyError, match="At least one scope"):
        issue_capability(_PRINCIPAL, [])


# ---------------------------------------------------------------------------
# 4. Expired capability → rejected
# ---------------------------------------------------------------------------

def test_expired_capability_rejected():
    # Issue with TTL overridden to 0 (already expired).
    with patch.object(settings, "mcp_capability_ttl_seconds", 0):
        token = issue_capability(_PRINCIPAL, ["transactions:read"])
    # Small sleep to ensure we're past the exp.
    time.sleep(0.05)
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_capability(token)


# ---------------------------------------------------------------------------
# 5. Tampered / wrong-key → rejected
# ---------------------------------------------------------------------------

def test_tampered_payload_rejected():
    token = issue_capability(_PRINCIPAL, ["transactions:read"])
    # Tamper with the payload portion of the JWT (second segment).
    parts = token.split(".")
    # Flip a char in the payload.
    tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"
    with pytest.raises(jwt.PyJWTError):
        verify_capability(tampered)


def test_wrong_secret_key_rejected():
    payload = {
        "uid": 42,
        "kid": 7,
        "scopes": ["transactions:read"],
        "jti": "test",
        "typ": _CAPABILITY_TOKEN_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=60),
    }
    token = jwt.encode(payload, "wrong-secret-key", algorithm=settings.jwt_algorithm)
    with pytest.raises(jwt.PyJWTError):
        verify_capability(token)


# ---------------------------------------------------------------------------
# 6. Type confusion across auth / action / capability tokens
# ---------------------------------------------------------------------------

def test_auth_access_token_rejected_as_capability():
    """A plain auth access token must fail ``verify_capability``.

    L3: each family now signs with its OWN HKDF key and a distinct ``aud``, so a
    token minted with the raw secret for the session audience fails capability
    verification at the signature/audience stage (a PyJWTError) — a strictly
    stronger rejection than the old ``typ``-only check."""
    payload = {
        "sub": "alice",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(jwt.PyJWTError):
        verify_capability(token)


def test_action_token_rejected_as_capability():
    """An ``assistant_action`` token must fail ``verify_capability`` (wrong aud +
    wrong signing key under L3)."""
    from server.src.services.assistant_service import ActionService

    action_token = ActionService.make_token(
        user_id=42,
        action="add_goal",
        params={"name": "test", "amount": 100, "date": "2026-12-31"},
    )
    with pytest.raises(jwt.PyJWTError):
        verify_capability(action_token)


def test_capability_token_rejected_as_action_token():
    """A capability token must fail ``ActionService.decode_token`` (the action leaf
    wraps the PyJWT signature/audience failure as ActionError)."""
    from server.src.services.assistant_service import ActionError, ActionService

    cap_token = issue_capability(_PRINCIPAL, ["transactions:read"])
    with pytest.raises(ActionError):
        ActionService.decode_token(cap_token)


def test_wrong_typ_with_correct_audience_still_rejected():
    """Defense-in-depth: even a token correctly signed with the MCP key + aud but
    carrying the wrong ``typ`` is rejected (the ``typ`` check survives L3)."""
    from server.src.services import token_keys

    forged = token_keys.encode(
        {
            "uid": 1,
            "typ": "not_a_capability",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
        },
        purpose=token_keys.AUD_MCP,
        audience=token_keys.AUD_MCP,
    )
    with pytest.raises(PolicyError, match="not a capability token"):
        verify_capability(forged)


# ---------------------------------------------------------------------------
# 7. Audit: record emits one line, no secrets, deterministic hash
# ---------------------------------------------------------------------------

def test_audit_record_emits_structured_line(caplog):
    """``record`` emits exactly one log line with user_id + key_id."""
    with caplog.at_level(logging.INFO, logger="mcp.audit"):
        record(
            user_id=42,
            key_id=7,
            resource="transactions:read",
            params={"start": "2026-01-01", "end": "2026-01-31"},
            decision="allow",
            latency_ms=12.345,
        )

    # Scope to the logger under test. This user_id has no row, so the DB write
    # fails a FK constraint — which now emits its own WARNING from
    # mcp_audit_store rather than being swallowed. That extra record is correct
    # behaviour (see test_mcp_audit_log.py), and counting every logger's records
    # would make this test fail for a reason it was never about. Worth noting the
    # inverse: this test passed for as long as that write failed in silence.
    audit_lines = [r for r in caplog.records if r.name == "mcp.audit"]
    assert len(audit_lines) == 1
    line = audit_lines[0].getMessage()
    parsed = json.loads(line)

    assert parsed["user_id"] == 42
    assert parsed["key_id"] == 7
    assert parsed["resource"] == "transactions:read"
    assert parsed["decision"] == "allow"
    assert parsed["latency_ms"] == 12.35  # rounded to 2 dp


def test_audit_no_raw_params_in_log(caplog):
    """Raw param values must NEVER appear in the audit line."""
    secret_params = {"api_key": "super_secret_value", "ssn": "123-45-6789"}
    with caplog.at_level(logging.INFO, logger="mcp.audit"):
        record(
            user_id=1,
            key_id=2,
            resource="test",
            params=secret_params,
            decision="allow",
        )

    line = caplog.records[0].getMessage()
    assert "super_secret_value" not in line
    assert "123-45-6789" not in line
    # But the hash is present.
    parsed = json.loads(line)
    assert len(parsed["params_hash"]) == 16


def test_audit_no_raw_key_in_log(caplog):
    """The key itself never appears — only the key_id integer."""
    with caplog.at_level(logging.INFO, logger="mcp.audit"):
        record(
            user_id=1,
            key_id=99,
            resource="test",
            decision="deny",
        )

    line = caplog.records[0].getMessage()
    assert "bdgt_live_" not in line
    parsed = json.loads(line)
    assert parsed["key_id"] == 99


def test_params_hash_deterministic_and_order_independent():
    """``{a:1, b:2}`` and ``{b:2, a:1}`` must produce the same hash."""
    h1 = _canonical_params_hash({"a": 1, "b": 2})
    h2 = _canonical_params_hash({"b": 2, "a": 1})
    assert h1 == h2
    assert len(h1) == 16


def test_params_hash_empty():
    assert _canonical_params_hash(None) == ""
    assert _canonical_params_hash({}) == ""
