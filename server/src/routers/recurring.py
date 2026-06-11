"""Router for projected recurring expenses.

Surfaces the "future expected" expense instances that ``RecurringService``
works out on read. Nothing is saved. The horizon defaults to the next 90 days,
and callers can override ``start`` and ``end`` (ISO ``YYYY-MM-DD``).
"""

from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.recurring_service import RecurringService

router = APIRouter(prefix="/recurring", tags=["recurring"])

_DEFAULT_HORIZON_DAYS = 90


@router.get("/projected/")
async def get_projected_expenses(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    start: Optional[date] = None,
    end: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Return the projected recurring expense instances across the horizon."""
    horizon_start = start or date.today()
    horizon_end = end or (horizon_start + timedelta(days=_DEFAULT_HORIZON_DAYS))
    return RecurringService(db).project_expenses(
        current_user.id, horizon_start, horizon_end
    )
