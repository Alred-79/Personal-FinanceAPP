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
from server.src.services.game.daily import DailyService, streak_view

router = APIRouter(prefix="/game", tags=["game"])


@router.get("/streak/")
async def get_streak(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The streak chip + ward slots + collectible tick. Reading writes nothing.

    The 'broken' concept does not exist in the data model, so it cannot leak
    here — a lapsed streak reads as ``rebuilding`` with ``best`` preserved.
    """
    return streak_view(db)


@router.post("/tick/collect/")
async def collect_tick(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Collect the accrued tick. Reveals the already-accrued amount and awards
    NOTHING extra — collect is presentation, not a rewarded action."""
    amount = DailyService(db).collect_tick(current_user)
    db.commit()
    return {"collected": amount}


@router.get("/bosses/")
async def list_bosses(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """List the user's debts (bosses) with their projected HP. The active boss
    carries its boss_state HP; others render as dormant silhouettes."""
    from server.src.services.game.liability_service import LiabilityService
    from server.src.services.game.boss import boss_view

    svc = LiabilityService(db)
    out = []
    for liab in svc.list(current_user):
        d = LiabilityService.to_dict(liab)
        d["boss"] = boss_view(db, liab.id)
        out.append(d)
    return {"bosses": out}


@router.get("/monsters/")
async def list_monsters(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The computed habit-monsters (<=2). A pure read; writes nothing."""
    from server.src.services.game.habit_monsters import detect_monsters

    return {"monsters": detect_monsters(db, current_user)}


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
