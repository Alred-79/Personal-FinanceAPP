"""Net worth router.

``GET /networth/`` returns the snapshot trend series and quietly records today's
snapshot while it's at it. ``POST /networth/snapshot/`` forces one right now,
which is handy to call after anything that changes a balance.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.money import cents_to_dollars
from server.src.services.auth_service import AuthService
from server.src.services.networth_service import NetWorthService

router = APIRouter(prefix="/networth", tags=["networth"])


@router.get("/")
async def get_networth(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Return the net worth trend series, recording today's snapshot on read."""
    return NetWorthService(db).get_series(current_user.id)


@router.post("/snapshot/")
async def create_snapshot(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Force a net worth snapshot for today and return its total in dollars."""
    snapshot = NetWorthService(db).record_snapshot(current_user.id)
    return {
        "date": snapshot.date,
        "total": cents_to_dollars(snapshot.total),
    }
