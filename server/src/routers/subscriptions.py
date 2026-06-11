"""Subscriptions router.

Surfaces the recurring charges we detect (last and next charge, cadence) for the
"Subscriptions" view and its "cancel?" nudges. Detection happens on read from
the user's expense history, and nothing is saved.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.subscription_service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/")
def get_subscriptions(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Return detected subscriptions, sorted by next expected charge date."""
    return SubscriptionService(db).list_subscriptions(current_user.id)
