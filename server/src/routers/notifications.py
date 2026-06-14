"""Notifications router.

Exposes the nudge feed inside the app that powers the UI bell. ``GET /notifications/``
regenerates fresh nudges (budget overruns + anomalies) before returning the
feed, so the bell is always current without a separate cron.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Goal as GoalORM,
    Notification as NotificationORM,
)
from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.money import cents_to_dollars
from server.src.services import action_tokens
from server.src.services.auth_service import AuthService
from server.src.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/")
def get_notifications(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    unread_only: bool = False,
    db: Session = Depends(get_db),
):
    """Regenerate nudges, then return the feed plus the unread count."""
    service = NotificationService(db)
    service.generate(current_user.id)
    return {
        "items": service.list(current_user.id, unread_only=unread_only),
        "unread_count": service.unread_count(current_user.id),
    }


@router.put("/{notification_id}/read/")
def mark_notification_read(
    notification_id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    if not NotificationService(db).mark_read(current_user.id, notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Notification marked as read"}


@router.put("/read-all/")
def mark_all_notifications_read(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    service = NotificationService(db)
    # Generate pending nudges first so "mark all read" really clears the bell:
    # otherwise a nudge whose condition already holds (an overrun this month)
    # would be created unread by the very next feed refresh.
    service.generate(current_user.id)
    count = service.mark_all_read(current_user.id)
    return {"message": f"Marked {count} notification(s) as read"}


@router.post("/{notification_id}/proposal-token/")
def mint_proposal_token(
    notification_id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Re-mint the one-tap confirm token for an above-threshold auto-fund proposal.

    Pillar 2B: when a rule firing exceeds the user's auto-execute threshold, the
    engine persists a durable ``rule_proposal`` notification (``ref`` =
    ``rule_proposal:{rule_id}:{goal_id}:{cents}``) but NOT a token — a 10-minute
    JWT baked into a durable row would go stale. This endpoint reconstructs the
    exact ``create_allocation`` params from the ref and mints a FRESH token on
    demand, so the user can approve whenever they get to it. The token is bound to
    THIS user and confirmed through the normal ``/assistant/actions/confirm/``
    path (replay-guarded, ownership-checked) — nothing moves until they approve.

    Re-validates goal ownership here so a deleted/foreign goal yields 404 rather
    than a token that fails closed at confirm.
    """
    note = db.execute(
        select(NotificationORM).where(
            NotificationORM.id == notification_id,
            NotificationORM.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if note.type != "rule_proposal" or not note.ref:
        raise HTTPException(
            status_code=400, detail="Not an approvable auto-fund proposal."
        )
    # ref shape: rule_proposal:<rule_id>:<goal_id>:<cents>
    parts = note.ref.split(":")
    if len(parts) != 4 or parts[0] != "rule_proposal":
        raise HTTPException(status_code=400, detail="Malformed proposal reference.")
    try:
        goal_id = int(parts[2])
        cents = int(parts[3])
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed proposal reference.")
    goal = db.execute(
        select(GoalORM.id, GoalORM.name).where(
            GoalORM.id == goal_id, GoalORM.user_id == current_user.id
        )
    ).one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Target goal no longer exists.")
    dollars = cents_to_dollars(cents)
    token = action_tokens.make_token(
        current_user.id,
        "create_allocation",
        {"goal_id": goal_id, "amount": dollars},
    )
    return {
        "token": token,
        "action": "create_allocation",
        "summary": (
            f"Set aside ${dollars:,.2f} toward goal '{goal.name}'"
        ),
        "amount": dollars,
        "goal_id": goal_id,
    }
