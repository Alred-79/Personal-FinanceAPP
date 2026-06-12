"""Game read surface (v4 package 04).

Read-only endpoints for the Keeper sheet: the four stats and the level/XP bar.
These are pure OUTPUTS derived from finance data + the event log — reading them
writes nothing (no engagement XP).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.game.stats import StatsService, player_xp
from server.src.services.game.xp import LEVEL_K

router = APIRouter(prefix="/game", tags=["game"])


@router.get("/keeper/")
async def get_keeper(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The Keeper sheet payload: stats + level/XP. Reading writes nothing."""
    stats = StatsService(db).compute(current_user)
    xp = player_xp(db)
    level = xp["level"]
    # XP needed for the next level boundary (for the progress bar).
    next_level_xp = (level + 1) ** 2 * LEVEL_K
    this_level_xp = level**2 * LEVEL_K
    span = max(next_level_xp - this_level_xp, 1)
    progress = max(0.0, min(1.0, (xp["xp"] - this_level_xp) / span))
    return {
        "stats": stats.to_dict(),
        "level": level,
        "xp": xp["xp"],
        "xp_into_level": xp["xp"] - this_level_xp,
        "xp_for_next": next_level_xp - this_level_xp,
        "level_progress": round(progress, 3),
    }
