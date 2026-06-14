"""Signed pending-action confirmation tokens — the propose→confirm leaf.

A write action is never executed inline. A "tool" only *proposes* a change and
mints a short-lived, signed JWT that fully describes it (``action`` + normalized
``params`` + a one-use ``jti``). The change happens only when that token is sent
back to ``/assistant/actions/confirm/`` and decoded here. Model proposes, user
approves, server runs it.

Why this is its OWN module (Pillar 2B, R7): minting used to live inside
``ActionService`` in ``assistant_service``. But the bounded auto-execute lane lets
the **rule engine** mint a money-affecting proposal from an *unattended* trigger
(a Plaid sync, no user in the loop). ``rule_engine`` cannot import
``assistant_service`` — ``assistant_service`` already imports the engine, so that
would be a cycle. Extracting the mint/decode pair into this dependency-free leaf
lets BOTH layers depend on the leaf, not on each other. ``ActionService``
re-exports ``make_token``/``decode_token`` for back-compat, so every existing
caller is unchanged.

This module imports only ``jwt`` and ``settings`` — never a service or a model —
so it can be imported from anywhere without an order hazard. An import-order test
(``test_action_tokens``) pins that the engine importing it creates no cycle with
the assistant layer.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt

from ..settings import settings

# The token ``typ`` discriminator. An auth access token and an action-confirm
# token are both JWTs signed with the same secret; this field is what makes them
# non-substitutable (``decode_token`` rejects anything whose ``typ`` differs).
ACTION_TOKEN_TYPE = "assistant_action"
# Tokens are deliberately short-lived: a proposal the user never acts on must not
# remain confirmable for long. The sync-triggered lane (2B) re-mints on demand
# from the persisted ``needs_confirmation`` RuleExecution rather than holding a
# long-lived token (see rule_engine).
ACTION_TOKEN_TTL = timedelta(minutes=10)


class ActionTokenError(ValueError):
    """A confirmation token is missing, malformed, expired, or the wrong type."""


def make_token(user_id: int, action: str, params: dict) -> str:
    """Mint a signed, single-use confirmation token for *action*.

    ``jti`` is a fresh random id; the confirm endpoint claims it once (via
    ``reserve_jti``) so a replay can't double-apply the write.
    """
    payload = {
        "uid": int(user_id),
        "typ": ACTION_TOKEN_TYPE,
        "jti": secrets.token_urlsafe(16),  # one-use id (replay guard)
        "action": action,
        "params": params,
        "exp": datetime.now(timezone.utc) + ACTION_TOKEN_TTL,
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_token(token: str) -> dict:
    """Verify + decode a confirmation token, or raise ``ActionTokenError``.

    Rejects an expired token, a bad signature, and — critically — any JWT whose
    ``typ`` isn't ``ACTION_TOKEN_TYPE`` (so an auth access token can never be
    substituted for an action-confirm token).
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise ActionTokenError(
            "This proposed action has expired; please ask again."
        )
    except jwt.PyJWTError:
        raise ActionTokenError("Invalid confirmation token.")
    if payload.get("typ") != ACTION_TOKEN_TYPE:
        raise ActionTokenError("Not an action-confirmation token.")
    return payload
