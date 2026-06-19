"""Plaid inbound webhook verification + dispatch (audit L1).

Plaid POSTs webhooks (``SYNC_UPDATES_AVAILABLE``, ``ITEM_LOGIN_REQUIRED``, …) to a
public endpoint. Because the endpoint is public, EVERY request must be
cryptographically verified before we trust it for *routing only* (never for data).

Verification (Plaid's scheme):
1. The ``Plaid-Verification`` header is a JWT signed ES256 with a key Plaid serves
   by ``kid`` via the authenticated ``/webhook_verification_key/get`` API.
2. The JWT body carries ``request_body_sha256``; we recompute SHA-256 over the RAW
   request bytes and constant-time compare. This binds the verified JWT to THIS
   body (the JWT itself contains no payload).
3. ``iat`` must be recent (replay defense).

NEVER log the JWT, the header, or any access token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time

import jwt
from cachetools import TTLCache

log = logging.getLogger(__name__)

# Reject a webhook whose verification JWT was issued more than this long ago.
_MAX_IAT_AGE_SECONDS = 300  # 5 min
# Cache verification keys by kid (Plaid rotates them; refetch on miss / expiry).
_KEY_CACHE: TTLCache = TTLCache(maxsize=64, ttl=3600)
_KEY_CACHE_LOCK = threading.Lock()


class WebhookVerificationError(Exception):
    """The webhook signature / body hash / freshness check failed."""


def _default_key_fetcher(kid: str) -> dict:
    from server.src.databridge.plaid_client import PlaidClient

    return PlaidClient().get_webhook_verification_key(kid)


class PlaidWebhookVerifier:
    """Verifies a Plaid webhook and returns its parsed body (routing only)."""

    def __init__(self, key_fetcher=_default_key_fetcher) -> None:
        self._fetch_key = key_fetcher

    def _resolve_key(self, kid: str):
        """The ES256 public key for *kid*, cached. Refetches on miss / expired JWK."""
        with _KEY_CACHE_LOCK:
            cached = _KEY_CACHE.get(kid)
        if cached is None:
            jwk = self._fetch_key(kid)  # may raise — caller maps to a 401
            # Plaid marks rotated-out keys with a non-null expired_at; don't cache
            # an already-expired key.
            if jwk.get("expired_at") is None:
                with _KEY_CACHE_LOCK:
                    _KEY_CACHE[kid] = jwk
            cached = jwk
        return jwt.PyJWK.from_dict(cached).key

    def verify(self, raw_body: bytes, jwt_header_value: str | None) -> dict:
        """Verify the webhook; return the parsed-from-raw JSON body on success.

        Raises ``WebhookVerificationError`` on ANY failure (missing/garbled header,
        wrong alg, bad signature, body-hash mismatch, stale iat).
        """
        if not jwt_header_value:
            raise WebhookVerificationError("missing Plaid-Verification header")
        try:
            header = jwt.get_unverified_header(jwt_header_value)
        except jwt.PyJWTError as exc:
            raise WebhookVerificationError("malformed verification JWT") from exc
        # Pin ES256 (PyJWT already rejects alg=none; pin explicitly to close
        # alg-substitution).
        if header.get("alg") != "ES256":
            raise WebhookVerificationError("unexpected JWT alg")
        kid = header.get("kid")
        if not kid:
            raise WebhookVerificationError("verification JWT missing kid")
        try:
            key = self._resolve_key(kid)
        except WebhookVerificationError:
            raise
        except Exception as exc:  # noqa: BLE001 — key fetch / parse failure
            raise WebhookVerificationError("could not resolve verification key") from exc

        try:
            claims = jwt.decode(
                jwt_header_value,
                key=key,
                algorithms=["ES256"],
                options={"require": ["iat"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise WebhookVerificationError("verification JWT invalid") from exc

        # Replay defense: reject an old (or far-future) iat.
        iat = claims.get("iat")
        now = int(time.time())
        if not isinstance(iat, (int, float)) or (now - iat) > _MAX_IAT_AGE_SECONDS:
            raise WebhookVerificationError("verification JWT too old")
        if iat - now > 60:  # small future-skew tolerance
            raise WebhookVerificationError("verification JWT issued in the future")

        # Body integrity: bind the verified JWT to THIS exact body.
        expected = claims.get("request_body_sha256")
        actual = hashlib.sha256(raw_body).hexdigest()
        if not isinstance(expected, str) or not hmac.compare_digest(expected, actual):
            raise WebhookVerificationError("request body hash mismatch")

        # Verified — parse the RAW body (trusted for ROUTING only, never data).
        try:
            return json.loads(raw_body)
        except ValueError as exc:
            raise WebhookVerificationError("webhook body is not JSON") from exc


# ── Dispatch ─────────────────────────────────────────────────────────────────

# webhook_codes (under webhook_type TRANSACTIONS) that should trigger a sync.
_SYNC_CODES = {
    "SYNC_UPDATES_AVAILABLE",
    "INITIAL_UPDATE",
    "HISTORICAL_UPDATE",
    "DEFAULT_UPDATE",
}
# ITEM webhook_codes that always warrant a re-link notice.
_RELINK_CODES = {"ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION"}


def dispatch(db, payload: dict) -> None:
    """Route a VERIFIED webhook payload to a sync or a re-link notice.

    The caller has already opened a session able to resolve the token by item_id
    (BYPASSRLS under RLS) — this binds the tenant once the user is known, then
    acts. Unknown items / unrecognized codes are logged no-ops (return 200 fast).
    """
    from sqlalchemy import select

    from server.src.db.models import Token as TokenORM
    from server.src.db.rls import set_tenant
    from server.src.services.plaid_service import (
        _RELINK_ERROR_CODES,
        PlaidService,
    )

    item_id = payload.get("item_id")
    webhook_type = payload.get("webhook_type")
    webhook_code = payload.get("webhook_code")
    if not item_id:
        log.info("plaid webhook: no item_id; ignoring")
        return

    token = db.execute(
        select(TokenORM).where(TokenORM.item_id == str(item_id))
    ).scalar_one_or_none()
    if token is None:
        # A webhook for an item we don't have (link-time race, or a pre-webhook
        # item with no item_id). 200 no-op so Plaid stops retrying.
        log.info("plaid webhook: unknown item_id; ignoring (type=%s)", webhook_type)
        return

    set_tenant(db, token.user_id)
    svc = PlaidService(db)

    if webhook_type == "TRANSACTIONS" and webhook_code in _SYNC_CODES:
        svc.sync_token(token)
        db.commit()
        return
    if webhook_type == "ITEM":
        if webhook_code in _RELINK_CODES:
            svc._notify_relink(token.user_id, token.id)
            db.commit()
            return
        if webhook_code == "ERROR":
            err = (payload.get("error") or {})
            if err.get("error_code") in _RELINK_ERROR_CODES:
                svc._notify_relink(token.user_id, token.id)
                db.commit()
            else:
                log.info("plaid webhook: ITEM ERROR code=%s; no notice", err.get("error_code"))
            return
    log.info(
        "plaid webhook: unhandled (type=%s code=%s); no-op", webhook_type, webhook_code
    )
