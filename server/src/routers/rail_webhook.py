"""Public rail settlement-webhook endpoint (Phase 2b, SANDBOX ONLY).

A rail POSTs settlement events (settled / failed / returned) here with no user
session, so this lives in its OWN router registered WITHOUT the tenant dependency
(like ``plaid_webhook``). It verifies an HMAC signature over the raw body, looks
the Bridge up by ``(rail, rail_ref)`` across tenants, and drives
``apply_settlement`` (idempotent per ``(rail_ref, event)`` and per event id).

The whole surface 404s unless ``rail_origination_enabled`` is set — there is no
production credential path in this slice.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from server.src.settings import settings
from server.src.services.assisted_action_service import AssistedActionService
from server.src.services.rails.webhook import (
    SIGNATURE_HEADER,
    WebhookVerificationError,
    verify,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/rails", tags=["rails-webhook"])


def _sessions():
    """Session factory that can see all tenants for the (rail, rail_ref) lookup.

    Under RLS the ``assisted_actions`` table is tenant-gated and the webhook has no
    user session, so reuse the scheduler's BYPASSRLS factory; without RLS
    (default / SQLite / CI) this is a plain session."""
    if settings.enable_rls:
        from server.src.scheduler import _scheduler_sessions

        return _scheduler_sessions()()
    from server.src.db.session import SessionLocal

    return SessionLocal()


@router.post("/webhook")
async def rail_webhook(request: Request):
    # The endpoint does not exist unless origination is enabled (sandbox-only).
    if not settings.rail_origination_enabled:
        raise HTTPException(status_code=404, detail="Not Found")

    # Read the RAW body BEFORE parsing — the signature binds to these exact bytes.
    raw = await request.body()
    header = request.headers.get(SIGNATURE_HEADER)
    try:
        evt = verify(raw, header, settings.increase_webhook_secret)
    except WebhookVerificationError:
        # Do NO work on an unverified request; don't echo which check failed.
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    db = _sessions()
    try:
        AssistedActionService(db).apply_settlement(
            evt.rail, evt.rail_ref, evt.event, event_id=evt.event_id
        )
        db.commit()
    except Exception:  # noqa: BLE001 — a handler failure must not surface to the rail
        db.rollback()
        log.exception("rail webhook apply_settlement failed")
    finally:
        db.close()
    # 200 even on an unknown ref (ignored) so the rail doesn't retry forever.
    return {"status": "received"}
