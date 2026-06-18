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

    # W4 reflection automation offer: ref shape ``rule_suggest:{kind}:goal:{goal_id}:{period}``.
    # On tap, mint a ``create_rule`` (allocate) token — propose-only: confirming
    # CREATES a standing rule (no money moves; nothing auto-fires). The ~amount is
    # re-derived from the user's verified history (it's intentionally NOT in the
    # ref, so a few-cent drift can't defeat dedup).
    if note.ref.startswith("rule_suggest:"):
        return _mint_rule_suggest_token(db, current_user.id, note.ref)

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


def _mint_rule_suggest_token(db: Session, user_id: int, ref: str) -> dict:
    """Mint a fresh ``create_rule`` (allocate) confirm token for a W4 reflection
    automation offer. Propose-only: confirming creates a standing rule; no money
    moves. Re-derives the ~amount + cadence from the user's verified history."""
    import statistics

    from server.src.services import action_reflection

    # ref shape: rule_suggest:{kind}:goal:{goal_id}:{period}
    parts = ref.split(":")
    if len(parts) != 5 or parts[0] != "rule_suggest" or parts[2] != "goal":
        raise HTTPException(status_code=400, detail="Malformed proposal reference.")
    kind = parts[1]
    period = parts[4]
    try:
        goal_id = int(parts[3])
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed proposal reference.")

    goal = db.execute(
        select(GoalORM.id, GoalORM.name).where(
            GoalORM.id == goal_id, GoalORM.user_id == user_id
        )
    ).one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Target goal no longer exists.")

    # Re-derive the ~amount from the verified actions of this (kind, goal).
    from server.src.db.models import AssistedAction as AssistedActionORM

    rows = (
        db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.user_id == user_id,
                AssistedActionORM.kind == kind,
                AssistedActionORM.status == "verified",
            )
        )
        .scalars()
        .all()
    )
    amounts = [
        r.amount_cents
        for r in rows
        if action_reflection._dest_label(r) == f"goal:{goal_id}"
    ]
    if not amounts:
        raise HTTPException(
            status_code=400, detail="This automation offer is no longer applicable."
        )
    amount_cents = int(statistics.median(sorted(amounts)))
    dollars = cents_to_dollars(amount_cents)

    token = action_tokens.make_token(
        user_id,
        "create_rule",
        {
            "action_type": "allocate",
            "name": f"Auto-fund {goal.name} ({period})"[:200],
            "conditions": [{"field": "type", "op": "eq", "value": "income"}],
            "amount": dollars,
            "target_id": goal_id,
        },
    )
    return {
        "token": token,
        "action": "create_rule",
        "summary": (
            f"Create an auto-fund rule: set aside ${dollars:,.2f} toward "
            f"'{goal.name}' when income posts"
        ),
        "amount": dollars,
        "goal_id": goal_id,
    }
