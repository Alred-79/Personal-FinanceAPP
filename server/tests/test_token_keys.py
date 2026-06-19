"""L3 — per-purpose JWT signing keys + aud/iss helper (token_keys)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from server.src.services import token_keys


def _exp():
    return datetime.now(timezone.utc) + timedelta(minutes=5)


def test_each_purpose_derives_a_distinct_key():
    keys = {
        p: token_keys.signing_key(p)
        for p in (token_keys.AUD_SESSION, token_keys.AUD_ACTION, token_keys.AUD_MCP)
    }
    assert len(set(keys.values())) == 3
    # Deterministic: same purpose → same key (no random salt).
    assert token_keys.signing_key(token_keys.AUD_MCP) == keys[token_keys.AUD_MCP]


def test_encode_decode_round_trip_stamps_aud_and_iss():
    tok = token_keys.encode({"uid": 7, "exp": _exp()}, token_keys.AUD_SESSION, token_keys.AUD_SESSION)
    payload = token_keys.decode(tok, token_keys.AUD_SESSION, token_keys.AUD_SESSION)
    assert payload["uid"] == 7
    assert payload["aud"] == token_keys.AUD_SESSION
    assert payload["iss"] == token_keys.ISSUER


def test_wrong_audience_is_rejected():
    """A token minted for one audience can't be verified for another, even though
    it's signed with that family's key."""
    tok = token_keys.encode({"uid": 1, "exp": _exp()}, token_keys.AUD_ACTION, token_keys.AUD_ACTION)
    # Decode demanding a different audience but the action key → InvalidAudience.
    with pytest.raises(jwt.InvalidAudienceError):
        token_keys.decode(tok, token_keys.AUD_ACTION, token_keys.AUD_SESSION)


def test_wrong_key_is_rejected():
    """A token signed under the action key fails decode under the MCP key."""
    tok = token_keys.encode({"uid": 1, "exp": _exp()}, token_keys.AUD_ACTION, token_keys.AUD_ACTION)
    with pytest.raises(jwt.PyJWTError):
        token_keys.decode(tok, token_keys.AUD_MCP, token_keys.AUD_MCP)


def test_aud_is_required():
    """A token lacking ``aud`` (e.g. a legacy token) is rejected by decode()."""
    # Sign with the session key but WITHOUT aud/iss (bypass encode()).
    from server.src.settings import settings

    bare = jwt.encode(
        {"uid": 1, "exp": _exp()},
        token_keys.signing_key(token_keys.AUD_SESSION),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        token_keys.decode(bare, token_keys.AUD_SESSION, token_keys.AUD_SESSION)
