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
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.src.db.models import AssistedAction as AssistedActionORM
from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.money import cents_to_dollars
from server.src.services.assisted_action_service import (
    AssistedActionError,
    AssistedActionService,
)
from server.src.services.auth_service import AuthService

router = APIRouter(prefix="/assisted-actions", tags=["assisted-actions"])


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
