"""Game read surface (v4 package 04).

Read-only endpoints for the Keeper sheet: the four stats and the level/XP bar.
These are pure OUTPUTS derived from finance data + the event log — reading them
writes nothing (no engagement XP).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
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


class _DrawerAsk(BaseModel):
    message: str


@router.post("/chronicler/ask/")
async def chronicler_ask(
    body: _DrawerAsk,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The Chronicler drawer: crisis screen → rate limit → assistant (buffered) →
    firewall, before anything reaches the client. Never streams raw model text;
    writes still flow through the assistant's propose→confirm path."""
    from datetime import date

    from server.src.services.game.drawer import (
        DAILY_MESSAGE_LIMIT,
        RATE_LIMIT_REFUSAL_FULL,
        RATE_LIMIT_REFUSAL_PLAIN,
        persona_system_prompt,
    )
    from server.src.services.game.firewall import (
        CRISIS_RESOURCE,
        is_crisis,
        screen_output,
    )

    mode = getattr(current_user, "game_mode", "off")
    plain = mode == "off"

    # 1. Crisis screen — bypasses the LLM entirely.
    if is_crisis(body.message):
        return {"text": CRISIS_RESOURCE["body"], "kind": "crisis",
                "persona": False, "ai_label": True, "blocked": False}

    # 2. Rate limit (per-process daily counter).
    count = _drawer_rate_bump(current_user.id, date.today().isoformat())
    if count > DAILY_MESSAGE_LIMIT:
        return {"text": RATE_LIMIT_REFUSAL_PLAIN if plain else RATE_LIMIT_REFUSAL_FULL,
                "kind": "refusal", "persona": not plain, "ai_label": True, "blocked": False}

    # 3. Assistant, buffered into one string (NOT streamed) so the firewall can
    #    screen the whole output before rendering. Reuse the assistant router's
    #    singleton (the drawer IS the existing assistant with a skin).
    from server.src.routers.assistant import assistant_service

    persona_system_prompt(mode)  # the skin (the assistant memory carries voice)
    chunks: list[str] = []
    try:
        async for piece in assistant_service.chat(current_user, body.message):
            chunks.append(piece)
    except Exception:
        return {"text": "The chronicle is unavailable right now.", "kind": "error",
                "persona": not plain, "ai_label": True, "blocked": False}
    raw = "".join(chunks)

    # 4. Firewall the output.
    verdict = screen_output(raw, plain=plain)
    if verdict.blocked:
        return {"text": verdict.safe_text, "kind": "redirect", "persona": not plain,
                "ai_label": True, "blocked": True}
    return {"text": raw, "kind": "message", "persona": not plain,
            "ai_label": True, "blocked": False}


# Per-process daily rate-limit counters for the drawer: {user_id: (date, count)}.
_DRAWER_COUNTS: dict[int, tuple[str, int]] = {}


def _drawer_rate_bump(user_id: int, today_iso: str) -> int:
    day, count = _DRAWER_COUNTS.get(user_id, (today_iso, 0))
    if day != today_iso:
        count = 0
    count += 1
    _DRAWER_COUNTS[user_id] = (today_iso, count)
    return count


@router.get("/chapter/")
async def get_chapter(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """This week's saga chapter (deterministic template via the API; the weekly
    batch job does real LLM generation). Off-mode users get nothing."""
    from datetime import date, timedelta

    from server.src.services.game.mode import should_generate_flavor
    from server.src.services.game.chronicler import generate_chapter

    if not should_generate_flavor(current_user):
        return {"chapter": None}
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    chapter = generate_chapter(db, current_user, week_start, week_end)
    db.commit()
    return {"chapter": chapter}


@router.get("/expedition/")
async def get_expedition(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """This month's expedition map (the forecast as a run map). A read — the
    immutable snapshot is drafted lazily on first view. Works in every mode; the
    client renders the same data as a calendar (off) or a map (full)."""
    import json
    from datetime import date

    from server.src.services.game.expedition import RunService, MODIFIERS, rank_modifiers

    today = date.today()
    month = f"{today.year}-{today.month:02d}"
    run = RunService(db).draft(current_user, month)
    db.commit()
    return {
        "month": month,
        "map": json.loads(run.map_json),
        "overlay": json.loads(run.overlay_json or "{}"),
        "modifier_key": run.modifier_key,
        "offered_modifiers": [
            {"key": k, "label": MODIFIERS[k].label}
            for k in rank_modifiers(db, current_user, month)
        ],
        "sealed": run.sealed_at is not None,
        "score": json.loads(run.score_json) if run.score_json else None,
    }


@router.get("/homestead/")
async def get_homestead(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The weekly Homestead reveal: projection hero + one commit action; the
    accrual line is omitted below $1.00. Engine math only — no LLM. Off-mode
    users get nothing."""
    from datetime import date

    from server.src.services.game.mode import should_generate_flavor
    from server.src.services.game.homestead import (
        check_milestones,
        multiplier,
        reveal_to_payload,
        weekly_reveal,
    )
    from server.src.services.game.grace import strain_mode

    if not should_generate_flavor(current_user):
        return {"reveal": None}
    today = date.today()
    check_milestones(db, current_user, today)
    # Conservative recent accrual — left at 0 here; the real job feeds it from
    # measured interest. (The trivial-sum suppression still applies.)
    reveal = weekly_reveal(db, current_user, today, recent_accrual_cents=0,
                           strain_mode=strain_mode(db))
    db.commit()
    return {"reveal": reveal_to_payload(reveal), "multiplier": multiplier(db)}


@router.get("/campaigns/")
async def get_campaign(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The quarterly campaign: arc, rank, milestone track. The payload carries
    NO time-remaining field — a countdown cannot render from data that does
    not exist (non-expiry is structural). Off-mode/holdout users get nothing;
    a killed feature serves its off-state."""
    from datetime import date

    from server.src.services.game import experiments
    from server.src.services.game.campaigns import CampaignService
    from server.src.services.game.mode import should_generate_flavor

    if (
        not should_generate_flavor(current_user)
        or experiments.is_killed("campaigns")
        or experiments.is_holdout(db, current_user.id)
    ):
        return {"campaign": None}
    view = CampaignService(db).view(current_user, date.today())
    db.commit()
    return {"campaign": view}


@router.get("/challenges/")
async def get_challenges(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Active + past challenge instances and sourced candidates. Reading
    writes nothing; judging happens in jobs, never on view."""
    from datetime import date

    from server.src.services.game import experiments
    from server.src.services.game.challenges import ChallengeService
    from server.src.services.game.mode import should_generate_flavor

    if (
        not should_generate_flavor(current_user)
        or experiments.is_killed("challenges")
        or experiments.is_holdout(db, current_user.id)
    ):
        return {"challenges": [], "candidates": []}
    svc = ChallengeService(db)
    return {
        "challenges": svc.view(current_user),
        "candidates": svc.source_candidates(current_user, date.today()),
    }


@router.get("/flags/")
async def get_flags(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Kill switches + holdout state for honest client rendering. A killed
    feature's UI vanishes; a holdout user's game UI is hidden entirely (the
    Money Spine — alerts, the number, what-if — is NEVER withheld)."""
    from server.src.services.game.experiments import flags_payload

    return flags_payload(db, current_user.id)


@router.get("/outcomes/")
async def get_outcomes(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The INTERNAL outcomes page (v0): per-cohort metric comparison with
    confidence intervals and the honesty footer. No marketing language;
    publishing anything beyond this internal view is an owner decision."""
    from server.src.services.game.metrics import outcomes_summary

    return outcomes_summary(db)
