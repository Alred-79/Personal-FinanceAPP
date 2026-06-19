"""MCP policy — scope enforcement, capability tokens, and PolicyError.

Pure functions, no network surface.  Every method is independently testable.

Token isolation (L3)
~~~~~~~~~~~~~~~~~~~~
Each token family now signs with its OWN HKDF-derived key and carries a distinct
``aud``/``iss`` (see ``server/src/services/token_keys.py``), on top of the older
``typ`` discriminator:

* **session** — auth access tokens (``aud="session"``, validated by ``AuthService``).
* **assistant_action** — action-confirm tokens (validated by ``ActionService``).
* **mcp** — capability tokens (``typ="mcp_capability"``, validated here).

``verify_capability`` decodes with the MCP key and REQUIRES ``aud="mcp"``, so an
auth or action token (different key + different audience) fails verification at
the signature/audience stage — and the residual ``typ`` check is the
defense-in-depth backstop for a token that somehow shares the MCP audience.
``ActionService.decode_token`` mirrors this for the action family.
"""

import secrets
from datetime import datetime, timedelta, timezone

import jwt

from server.src.mcp.principal import Principal
from server.src.services import token_keys
from server.src.settings import settings


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class PolicyError(Exception):
    """Raised when a principal is not allowed to perform an action.

    Callers map this to HTTP 403 or the MCP "forbidden" error code.
    """


# ---------------------------------------------------------------------------
# Scope gate
# ---------------------------------------------------------------------------

_CAPABILITY_TOKEN_TYPE = "mcp_capability"


def require(principal: Principal, scope: str) -> None:
    """Raise ``PolicyError`` if *scope* is not in *principal.scopes*."""
    if scope not in principal.scopes:
        raise PolicyError(
            f"Scope '{scope}' is required but the principal only has "
            f"{sorted(principal.scopes)}."
        )


# ---------------------------------------------------------------------------
# Capability tokens
# ---------------------------------------------------------------------------

def issue_capability(principal: Principal, scopes: list[str]) -> str:
    """Mint a short-lived, signed capability token.

    * Every scope in *scopes* must be present in ``principal.scopes``
      (no escalation).
    * At least one scope is required.

    Returns the encoded JWT string.
    """
    if not scopes:
        raise PolicyError("At least one scope is required for a capability token.")

    requested = set(scopes)
    available = set(principal.scopes)
    escalation = requested - available
    if escalation:
        raise PolicyError(
            f"Scope escalation denied: {sorted(escalation)} not in "
            f"principal scopes {sorted(available)}."
        )

    payload = {
        "uid": principal.user_id,
        "kid": principal.key_id,
        "scopes": sorted(scopes),  # deterministic for testing
        "jti": secrets.token_urlsafe(16),
        "typ": _CAPABILITY_TOKEN_TYPE,
        "exp": datetime.now(timezone.utc)
        + timedelta(seconds=settings.mcp_capability_ttl_seconds),
    }
    # L3: MCP HKDF key + aud, so a capability token can't satisfy the session or
    # action audience even with the shared master secret.
    return token_keys.encode(
        payload, purpose=token_keys.AUD_MCP, audience=token_keys.AUD_MCP
    )


def verify_capability(token: str) -> dict:
    """Decode + verify a capability token.

    Returns the payload dict on success.  Raises on any failure:
    * ``PolicyError`` for type-confusion (wrong ``typ``).
    * ``jwt.ExpiredSignatureError`` for expired tokens.
    * ``jwt.PyJWTError`` for tampered / invalid tokens.
    """
    try:
        payload = token_keys.decode(
            token, purpose=token_keys.AUD_MCP, audience=token_keys.AUD_MCP
        )
    except jwt.ExpiredSignatureError:
        raise
    except jwt.PyJWTError:
        raise

    if payload.get("typ") != _CAPABILITY_TOKEN_TYPE:
        raise PolicyError(
            f"Token type '{payload.get('typ')}' is not a capability token."
        )
    return payload
