"""Notifications router.

Exposes the nudge feed inside the app that powers the UI bell. ``GET /notifications/``
regenerates fresh nudges (budget overruns + anomalies) before returning the
feed, so the bell is always current without a separate cron.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
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
    count = NotificationService(db).mark_all_read(current_user.id)
    return {"message": f"Marked {count} notification(s) as read"}
