"""Per-purpose JWT signing keys + audience/issuer constants (audit L3).

Before L3 every JWT family — session access tokens, assistant-action confirm
tokens, MCP capability tokens — was signed with the SAME ``jwt_secret_key`` and
separated only by a ``typ`` claim. PyJWT rejects ``alg=none`` so classic
alg-confusion was already closed, but one missed ``typ`` check anywhere would be
a full type-confusion bypass.

L3 hardens this two ways:

1. **Distinct ``aud`` + ``iss``** per family, REQUIRED at verify time (in addition
   to the existing ``typ`` check). A token minted for one audience can't satisfy
   another's ``audience=`` check even with the shared secret.
2. **HKDF per-purpose signing keys** derived from the master secret. Each family
   signs/verifies with its OWN derived key, so leaking one purpose's verification
   context (or a bug that exposes a derived key) cannot forge another family's
   tokens.

This module is dependency-free (only ``jwt`` + ``cryptography`` + ``settings``) so
every token leaf can import it without an order hazard.
"""

from __future__ import annotations

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..settings import settings

ISSUER = "budget-ai"

# Purpose -> audience. The purpose string also salts the HKDF derivation, so the
# audience and the signing key are bound to the same label.
AUD_SESSION = "session"
AUD_ACTION = "assistant_action"
AUD_MCP = "mcp"


def signing_key(purpose: str) -> bytes:
    """HKDF-derive a 32-byte signing key for *purpose* from the master secret.

    Deterministic (no random salt) so every process derives the same key without
    coordination; the per-purpose ``info`` label gives each family an independent
    key. HS256 takes raw bytes, so we return the 32-byte HKDF output directly.
    """
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"budget-ai/jwt/{purpose}".encode("utf-8"),
    ).derive(settings.jwt_secret_key.encode("utf-8"))


def encode(payload: dict, purpose: str, audience: str) -> str:
    """Sign *payload* for a family: stamps ``aud``/``iss`` and uses the derived key."""
    body = {**payload, "aud": audience, "iss": ISSUER}
    return jwt.encode(body, signing_key(purpose), algorithm=settings.jwt_algorithm)


def decode(token: str, purpose: str, audience: str, *, require_exp: bool = True) -> dict:
    """Verify *token* for a family: derived key + required ``aud`` (+ ``iss``).

    Raises the underlying ``jwt`` errors (caller maps them). ``iss`` is verified;
    ``aud`` is both verified and required so a token minted for another audience
    is rejected here even though the secret is shared.
    """
    require = ["aud"]
    if require_exp:
        require.append("exp")
    return jwt.decode(
        token,
        signing_key(purpose),
        algorithms=[settings.jwt_algorithm],
        audience=audience,
        issuer=ISSUER,
        options={"require": require, "verify_aud": True, "verify_iss": True},
    )
