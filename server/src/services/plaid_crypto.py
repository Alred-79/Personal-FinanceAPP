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

# Ciphertext format markers.
#   v1 — ``enc:v1:<fernet>``           (no key fingerprint; the original Step-08)
#   v2 — ``enc:v2:<keyid>:<fernet>``   (L6 — embeds an 8-hex key fingerprint so a
#        row records WHICH key encrypted it, enabling graceful rotation)
# Both are recognized on read; new writes use v2. A value with neither prefix is
# treated as a legacy plaintext token (pre-Step-08), so reads degrade gracefully
# on a half-migrated DB.
_ENC_PREFIX = "enc:v1:"
_ENC_PREFIX_V2 = "enc:v2:"


def _derive_key_from_secret(secret: str) -> bytes:
    """Deterministically derive a 32-byte urlsafe-base64 Fernet key from *secret*."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest)


def _keyid(key: bytes) -> str:
    """A short, stable fingerprint of a Fernet key (first 8 hex of SHA-256).

    Identifies a key in v2 ciphertext WITHOUT revealing it — the fingerprint is a
    one-way hash of the urlsafe-base64 key bytes, so it leaks nothing usable.
    """
    return hashlib.sha256(key).hexdigest()[:8]


def _active_key() -> bytes:
    """The urlsafe-base64 Fernet key bytes used for NEW encryption.

    Explicit ``plaid_token_key`` when set, else derived from ``jwt_secret_key``.
    Fails closed in production (B3) when neither a dedicated key is set nor it is
    safe to derive one. Lazy (first use), never at import.
    """
    explicit = getattr(settings, "plaid_token_key", None)
    if explicit:
        return explicit.encode("utf-8") if isinstance(explicit, str) else explicit
    # B3 — fail closed in production: deriving the Fernet key from jwt_secret_key
    # means rotating that secret (routine credential hygiene) would brick every
    # stored Plaid token forever. In production with Plaid configured, REQUIRE a
    # dedicated PLAID_TOKEN_KEY so the two rotate independently.
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
    return _derive_key_from_secret(settings.jwt_secret_key)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """The process-wide ACTIVE Fernet (new writes). Built once from settings.

    Cached so we don't re-derive on every token operation. Tests that need a
    different key clear this cache (``_fernet.cache_clear()``) — and should also
    clear ``_key_map`` / ``_active_keyid``.
    """
    return Fernet(_active_key())


@lru_cache(maxsize=1)
def _active_keyid() -> str:
    """Fingerprint of the active key — stamped into v2 ciphertext on write."""
    return _keyid(_active_key())


@lru_cache(maxsize=1)
def _key_map() -> dict[str, Fernet]:
    """All keys available for DECRYPTION, keyed by fingerprint.

    The active key plus any ``plaid_token_keys_retired`` (decrypt-only, for a
    graceful rotation). A v2 ciphertext is decrypted by the key matching its
    embedded ``keyid``; v1 / unknown-keyid falls back to trying every key (each
    attempt is authenticated, so a wrong key fails cleanly).
    """
    keys: dict[str, Fernet] = {}
    active = _active_key()
    keys[_keyid(active)] = Fernet(active)
    retired = getattr(settings, "plaid_token_keys_retired", None)
    if retired:
        for raw in retired.split(","):
            raw = raw.strip()
            if not raw:
                continue
            kb = raw.encode("utf-8")
            keys.setdefault(_keyid(kb), Fernet(kb))
    return keys


def reset_key_cache() -> None:
    """Clear all key caches together. Call after changing key settings (tests, or
    the re-encrypt command swapping the active key)."""
    _fernet.cache_clear()
    _active_keyid.cache_clear()
    _key_map.cache_clear()


def is_encrypted(value: str | None) -> bool:
    """Whether *value* is a Step-08 ciphertext (v1 or v2) vs a legacy plaintext."""
    return bool(value) and (
        value.startswith(_ENC_PREFIX) or value.startswith(_ENC_PREFIX_V2)
    )  # type: ignore[union-attr]


def encrypt(plaintext: str) -> str:
    """Encrypt a Plaid access token for storage. Returns a v2 keyid-stamped ciphertext."""
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{_ENC_PREFIX_V2}{_active_keyid()}:{token}"


def _decrypt_token(ciphertext: str, keyid: str | None) -> str:
    """Decrypt a bare Fernet token, choosing the key by *keyid* when known.

    Falls back to trying every key in the map (v1 has no keyid; a key may have
    been retired/renamed). Raises ``InvalidToken`` if none succeed.
    """
    raw = ciphertext.encode("utf-8")
    keys = _key_map()
    if keyid and keyid in keys:
        return keys[keyid].decrypt(raw).decode("utf-8")
    # No keyid (v1), or a keyid we don't recognize: try each key. Fernet's auth
    # tag makes a wrong-key attempt fail cleanly, so this can't return garbage.
    last_exc: InvalidToken | None = None
    for fernet in keys.values():
        try:
            return fernet.decrypt(raw).decode("utf-8")
        except InvalidToken as exc:
            last_exc = exc
    raise last_exc if last_exc is not None else InvalidToken("no key available")


def decrypt(stored: str) -> str:
    """Recover the plaintext Plaid access token from its stored form.

    Handles v2 (``enc:v2:<keyid>:``) and v1 (``enc:v1:``) ciphertext, and tolerates
    a legacy *plaintext* token (no prefix) so a half-migrated DB still syncs —
    such a value is returned unchanged unless ``plaid_require_encrypted_tokens``
    is on (then it hard-fails). A prefixed value that fails to decrypt under every
    available key (wrong key / tampering) raises ``InvalidToken`` so the failure
    is loud, never a silent wrong-token call to Plaid.
    """
    if not is_encrypted(stored):
        if getattr(settings, "plaid_require_encrypted_tokens", False):
            # Migration is declared complete: a plaintext token here is a bug or
            # a tampered row, not an expected pre-migration value. Fail loud.
            raise InvalidToken(
                "Plaintext Plaid token encountered while "
                "plaid_require_encrypted_tokens is enabled."
            )
        # Legacy plaintext (pre-migration) — return as-is. The one-shot migration
        # encrypts these; until then we must not break sync.
        return stored
    if stored.startswith(_ENC_PREFIX_V2):
        rest = stored[len(_ENC_PREFIX_V2):]
        keyid, _, ciphertext = rest.partition(":")
        return _decrypt_token(ciphertext, keyid)
    # v1: no embedded keyid.
    ciphertext = stored[len(_ENC_PREFIX):]
    return _decrypt_token(ciphertext, None)
