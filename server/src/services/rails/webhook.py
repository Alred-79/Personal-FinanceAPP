"""Rail settlement-webhook verification + parsing (Phase 2b, SANDBOX ONLY).

A rail POSTs a settlement event (settled / failed / returned) to our public
webhook endpoint. We verify an HMAC-SHA256 signature over the RAW body against
``increase_webhook_secret`` (constant-time), then parse a normalized event the
rail-agnostic ``AssistedActionService.apply_settlement`` can drive.

The normalized event shape (the sandbox harness POSTs this directly; mapping a
raw provider event into it is a thin per-rail concern we keep here):

    {"id": "<event_id>", "rail": "increase", "rail_ref": "<transfer_id>",
     "event": "settled" | "failed" | "returned", "detail": {...optional...}}
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Optional


class WebhookVerificationError(Exception):
    """The signature was missing, malformed, or did not match the raw body."""


# Header the rail signs the body with (simplified sandbox scheme: hex HMAC-SHA256).
SIGNATURE_HEADER = "increase-webhook-signature"
_VALID_EVENTS = frozenset({"settled", "failed", "returned"})


@dataclass(frozen=True)
class SettlementEvent:
    event_id: str
    rail: str
    rail_ref: str
    event: str


def sign(raw: bytes, secret: str) -> str:
    """Hex HMAC-SHA256 of *raw* under *secret* (used by tests + the rail)."""
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def verify(raw: bytes, header: Optional[str], secret: str) -> SettlementEvent:
    """Verify the signature over *raw* and parse a ``SettlementEvent``.

    Fails CLOSED: an empty secret, a missing/garbled header, a bad signature, or a
    malformed/unknown event all raise ``WebhookVerificationError`` (no work done).
    """
    if not secret:
        raise WebhookVerificationError("webhook secret not configured")
    if not header:
        raise WebhookVerificationError("missing signature header")
    expected = sign(raw, secret)
    if not hmac.compare_digest(expected, header.strip()):
        raise WebhookVerificationError("signature mismatch")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookVerificationError(f"invalid JSON body: {exc}")
    if not isinstance(body, dict):
        raise WebhookVerificationError("body is not an object")

    event = str(body.get("event") or "")
    rail = str(body.get("rail") or "")
    rail_ref = str(body.get("rail_ref") or "")
    event_id = str(body.get("id") or "")
    if event not in _VALID_EVENTS:
        raise WebhookVerificationError(f"unknown event: {event!r}")
    if not rail or not rail_ref or not event_id:
        raise WebhookVerificationError("missing rail / rail_ref / id")
    return SettlementEvent(
        event_id=event_id, rail=rail, rail_ref=rail_ref, event=event
    )
