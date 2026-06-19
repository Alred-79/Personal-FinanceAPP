"""Public Plaid inbound-webhook endpoint (audit L1).

Kept in its OWN router (separate from the authed ``plaid_router``) so it is
registered WITHOUT the tenant dependency — Plaid calls it with no user session.
The endpoint verifies the signature, returns 200 fast, and does the real work
(sync / notify) in a background task with its own session. Verification failures
return 401 and do no work.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from server.src.limiter import limiter
from server.src.settings import settings
from server.src.services.plaid_webhook import (
    PlaidWebhookVerifier,
    WebhookVerificationError,
    dispatch,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/plaid", tags=["plaid-webhook"])

_verifier = PlaidWebhookVerifier()


def _process_webhook(payload: dict) -> None:
    """Resolve the item→token and dispatch, in a fresh session.

    Under RLS the ``tokens`` table is tenant-gated, so the item→token lookup must
    run on a session that can see all tenants — reuse the scheduler's BYPASSRLS
    session factory. Without RLS (default / SQLite / CI) this is a plain session.
    """
    if settings.enable_rls:
        from server.src.scheduler import _scheduler_sessions

        db = _scheduler_sessions()()
    else:
        from server.src.db.session import SessionLocal

        db = SessionLocal()
    try:
        dispatch(db, payload)
    except Exception:  # noqa: BLE001 — a dispatch failure must not surface to Plaid
        db.rollback()
        log.exception("plaid webhook dispatch failed")
    finally:
        db.close()


@router.post("/webhook")
@limiter.limit(lambda: settings.plaid_webhook_rate_limit)
async def plaid_webhook(request: Request, background_tasks: BackgroundTasks):
    # Read the RAW body BEFORE any parsing — the signature binds to these exact
    # bytes (a re-serialized dict would change them and break the SHA-256 check).
    raw = await request.body()
    header = request.headers.get("plaid-verification")
    try:
        payload = _verifier.verify(raw, header)
    except WebhookVerificationError:
        # Do NO work on an unverified request. Don't echo the reason (avoid
        # leaking which check failed); never log the JWT.
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    # 200 fast; the heavy work (sync / notify) runs after the response. Plaid
    # retries non-2xx, so returning 200 here avoids duplicate deliveries; the work
    # is idempotent (global plaid_transaction_id index + ref-deduped notices).
    background_tasks.add_task(_process_webhook, payload)
    return {"status": "received"}
