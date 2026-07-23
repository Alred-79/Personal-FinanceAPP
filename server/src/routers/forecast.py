"""Forecast router. Projects your balance over a horizon.

Powers the Overview cashflow widget and "will I make rent?" style questions.
The horizon defaults to the next 30 days. Callers can override ``days`` or pass
an explicit ``start`` and ``end`` (ISO ``YYYY-MM-DD``).
"""

from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.forecast_service import ForecastService
from server.src.services.forecast_evidence_service import ForecastEvidenceService
from server.src.settings import settings

router = APIRouter(prefix="/forecast", tags=["forecast"])

_DEFAULT_HORIZON_DAYS = 30
_MAX_HORIZON_DAYS = 365


@router.get("/")
async def get_forecast(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    days: int = Query(_DEFAULT_HORIZON_DAYS, ge=1, le=_MAX_HORIZON_DAYS),
    start: Optional[date] = None,
    end: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Return a projected balance timeline plus a summary over the horizon."""
    horizon_start = start or date.today()
    horizon_end = end or (horizon_start + timedelta(days=days))
    return ForecastService(db).forecast(
        current_user.id, horizon_start, horizon_end, include_burn=True
    )


@router.get("/evidence/")
async def get_forecast_evidence(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Owner-only descriptive evidence; never a calibration/deployment claim."""
    if not settings.forecast_evidence_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    return ForecastEvidenceService(db).summary(current_user.id)
