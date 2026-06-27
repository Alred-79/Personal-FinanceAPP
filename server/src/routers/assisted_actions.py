"""Assisted Action Bridge router (Pillar 2C).

The Bridge object itself is CREATED through the assistant's propose→confirm flow
(``propose_assisted_action``) or from a proactive finding; this router manages the
human side of its lifecycle: list open Bridges, mark one acknowledged ("I'm doing
it"), confirmed_done ("I did it" — provisional until the next sync verifies it),
or dismissed. Verification itself is NOT a user action — it happens
deterministically in ``plaid_service.sync_token`` → ``reconcile``.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.src.db.models import AssistedAction as AssistedActionORM
from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.money import cents_to_dollars
from server.src.services import action_tokens
from server.src.services.assisted_action_service import (
    AssistedActionError,
    AssistedActionService,
    EXECUTE_TOKEN_ACTION,
)
from server.src.services.auth_service import AuthService
from server.src.services.rails import IncreaseAdapter, RailError
from server.src.services.rails.base import UnresolvedFundingResolver
from server.src.settings import settings

router = APIRouter(prefix="/assisted-actions", tags=["assisted-actions"])


def _require_origination_enabled() -> None:
    """Hard 404 when the master flag is off — the execute surface does not exist
    in any environment that hasn't opted in (it is SANDBOX-ONLY; see
    docs/PHASE2A-SANDBOX-IMPLEMENTATION.md)."""
    if not settings.rail_origination_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


class ExecuteRequest(BaseModel):
    confirmation_token: str


def _to_dict(b: AssistedActionORM) -> dict[str, Any]:
    try:
        how = json.loads(b.how_json or "{}")
    except (TypeError, ValueError):
        how = {}
    return {
        "id": b.id,
        "kind": b.kind,
        "amount": cents_to_dollars(b.amount_cents),
        "source_ref": b.source_ref,
        "dest_ref": b.dest_ref,
        "rationale": b.rationale,
        "how": how,
        "status": b.status,
        "settlement_status": b.settlement_status,
        # Phase 2a–2b sandbox origination fields (NULL on every manual Bridge).
        "rail": b.rail,
        "rail_ref": b.rail_ref,
        "created_at": b.created_at,
        "resolved_at": b.resolved_at,
    }


@router.get("/")
def list_assisted_actions(
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    open_only: bool = False,
    db: Session = Depends(get_db),
):
    """List the user's Bridges (newest first); ``open_only`` hides resolved ones."""
    items = AssistedActionService(db).list(current_user.id, open_only=open_only)
    return [_to_dict(b) for b in items]


def _transition(db: Session, user_id: int, action_id: int, op: str):
    svc = AssistedActionService(db)
    try:
        fn = getattr(svc, op)
        bridge = fn(user_id, action_id)
    except AssistedActionError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    db.flush()
    return _to_dict(bridge)


@router.post("/{action_id}/acknowledge/")
def acknowledge(
    action_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """User tapped 'Do it in my bank' — they're acting on it."""
    return _transition(db, current_user.id, action_id, "acknowledge")


@router.post("/{action_id}/done/")
def mark_done(
    action_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """User tapped 'I did it' — PROVISIONAL; the sync reconciliation verifies it."""
    return _transition(db, current_user.id, action_id, "mark_done")


@router.post("/{action_id}/dismiss/")
def dismiss(
    action_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """User dismissed the Bridge."""
    return _transition(db, current_user.id, action_id, "dismiss")


# ── Phase 2a–2b rail origination (SANDBOX ONLY; flag-gated, off by default) ────
# These two endpoints 404 entirely unless ``rail_origination_enabled`` is set.
# ``execute()`` is reachable ONLY here, from an authenticated user — it is NOT an
# assistant tool and NOT on the MCP surface (the model proposes, never sends).


@router.post("/{action_id}/execute-token/")
def mint_execute_token(
    action_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Mint the single-use, short-TTL confirmation token for THIS Bridge.

    Server-side only (the agent can never mint it). Bound to ``(action_id,
    amount_cents)`` so it can't be replayed against a different action or after the
    amount changes. The client sends it straight back to ``/execute/``."""
    _require_origination_enabled()
    svc = AssistedActionService(db)
    try:
        bridge = svc._own(current_user.id, action_id)
    except AssistedActionError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    token = action_tokens.make_token(
        current_user.id,
        EXECUTE_TOKEN_ACTION,
        {"action_id": bridge.id, "amount_cents": bridge.amount_cents},
    )
    return {"confirmation_token": token, "amount": cents_to_dollars(bridge.amount_cents)}


@router.post("/{action_id}/execute/")
def execute(
    action_id: int,
    body: ExecuteRequest,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Originate the Bridge's real money movement at the (sandbox) rail.

    A ``RailError`` — including the expected "no funding source yet" case (the 2a
    resolver always raises until 2c onboarding exists) — surfaces as 422 so the UI
    can fall back to the manual "do it in your bank" path. Nothing is half-done: on
    any error the Bridge keeps ``settlement_status=None`` and stays actionable."""
    _require_origination_enabled()
    svc = AssistedActionService(db)
    try:
        bridge = svc.execute(
            current_user.id,
            action_id,
            rail=IncreaseAdapter(),
            confirmation_token=body.confirmation_token,
            funding=UnresolvedFundingResolver(),
        )
    except RailError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.flush()
    return _to_dict(bridge)
