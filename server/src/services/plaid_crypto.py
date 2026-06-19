"""Symmetric encryption for the Plaid access token at rest (Step 08).

The Plaid access token is the single most sensitive credential in the system:
it grants read access to the user's real bank. The app's own MCP keys and
refresh tokens are SHA-256 hashed, but a Plaid token must be *recoverable* (we
hand it back to Plaid on every sync), so a one-way hash is impossible. We
encrypt it with Fernet (AES-128-CBC + HMAC, authenticated) so a copied DB file
is ciphertext, not cleartext bank access.

Key source (in priority order):
1. ``settings.plaid_token_key`` — an explicit Fernet key (urlsafe-base64, 32
   bytes) supplied via env. The production way: rotate independently of the JWT
   secret.
2. Derived from ``settings.jwt_secret_key`` — when no dedicated key is set we
   deterministically derive a Fernet key from the existing JWT secret (SHA-256 →
   urlsafe-base64). This keeps single-user/dev deployments working with no extra
   config while still encrypting at rest. The derivation is documented so an
   operator can move to a dedicated key without losing access (decrypt+re-encrypt
   via :func:`encrypt`).

NEVER log the decrypted token. Callers decrypt only at the boundary right before
a Plaid API call.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from server.src.settings import settings

# A short, stable prefix marking a value as Step-08 Fernet ciphertext. Lets the
# read path distinguish an already-encrypted token (post-migration) from a
# legacy plaintext token (pre-migration) WITHOUT a schema flag, so reads degrade
# gracefully on a half-migrated DB.
_ENC_PREFIX = "enc:v1:"


def _derive_key_from_secret(secret: str) -> bytes:
    """Deterministically derive a 32-byte urlsafe-base64 Fernet key from *secret*."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """The process-wide Fernet, built once from settings.

    Cached so we don't re-derive on every token operation. Tests that need a
    different key can clear this cache (``_fernet.cache_clear()``).
    """
    explicit = getattr(settings, "plaid_token_key", None)
    if explicit:
        # An explicit key must already be a valid Fernet key; fail loud at first
        # use rather than silently mis-encrypting.
        return Fernet(explicit.encode("utf-8") if isinstance(explicit, str) else explicit)
    # B3 — fail closed in production: deriving the Fernet key from jwt_secret_key
    # means rotating that secret (routine credential hygiene) would brick every
    # stored Plaid token forever. In production with Plaid configured, REQUIRE a
    # dedicated PLAID_TOKEN_KEY so the two rotate independently. This check is
    # lazy (first use), NOT at import, so it never breaks test collection / dev
    # startup. Dev / self-host keep the convenient derivation.
    if (
        settings.environment.lower() == "production"
        and getattr(settings, "plaid_client_id", None)
    ):
        raise RuntimeError(
            "PLAID_TOKEN_KEY must be set in production: deriving the token "
            "encryption key from JWT_SECRET_KEY would make every stored Plaid "
            "token undecryptable if the JWT secret is ever rotated. Set a "
            "dedicated PLAID_TOKEN_KEY (and set it BEFORE rotating JWT_SECRET_KEY)."
        )
    return Fernet(_derive_key_from_secret(settings.jwt_secret_key))


def is_encrypted(value: str | None) -> bool:
    """Whether *value* is a Step-08 ciphertext (vs a legacy plaintext token)."""
    return bool(value) and value.startswith(_ENC_PREFIX)  # type: ignore[union-attr]


def encrypt(plaintext: str) -> str:
    """Encrypt a Plaid access token for storage. Returns a prefixed ciphertext."""
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return _ENC_PREFIX + token


def decrypt(stored: str) -> str:
    """Recover the plaintext Plaid access token from its stored form.

    Tolerates a legacy *plaintext* token (no prefix) so a half-migrated DB still
    syncs — such a value is returned unchanged. A prefixed value that fails to
    decrypt (wrong key / tampering) raises ``InvalidToken`` so the failure is
    loud, never a silent wrong-token call to Plaid.
    """
    if not is_encrypted(stored):
        # Legacy plaintext (pre-migration) — return as-is. The one-shot migration
        # encrypts these; until then we must not break sync.
        return stored
    ciphertext = stored[len(_ENC_PREFIX):]
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:  # pragma: no cover - surfaced loudly to the caller
        raise
