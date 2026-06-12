"""The Homestead — the weekly/monthly reveal (v4 §6.5, the R2 redesign).

The hero is the FORWARD PROJECTION with a one-tap commit (never a trivial-sum
ticker). The supporting accrual line appears ONLY when it clears $1.00 for the
period — below that the key is OMITTED entirely (never "you earned $0.04"). All
projection math is the engine's, using conservative recent-accrual rates, never
optimistic APY and never the LLM.

Milestone multipliers are a ratchet: crossing a real threshold (first $500
buffer, 1-month runway, 3-month runway) grants a permanent homestead-XP multiplier
step; dropping back below NEVER removes it (no punishment).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from ...models import UserInDB
from . import folds as folds_mod
from .events import GameEventDraft, record_events, register_event_type

HOMESTEAD_STATE = "homestead_state"
TRIVIAL_SUM_CENTS = 100  # accrual lines below $1.00 are suppressed entirely

register_event_type("MilestoneReached", 1)

# Real milestone thresholds → permanent homestead-XP multiplier tier (+25%/tier).
# (buffer $500, 1-month runway, 3-month runway.)
MILESTONES = [
    ("buffer_500", 50000, "first $500 set aside"),
    ("runway_1mo", None, "one month of runway"),
    ("runway_3mo", None, "three months of runway"),
]
MULT_STEP = 0.25


@dataclass
class WeeklyReveal:
    projection_date: str
    projection_cents: int
    commit_action: dict  # exactly one (R14: reachable default, one button)
    accrual_line_cents: Optional[int]  # None when suppressed (< $1.00)


def _state(session: Session) -> dict:
    return folds_mod.kv_get(session, HOMESTEAD_STATE, "state") or {
        "tiers": [],  # milestone keys reached (ratchet)
    }


def _put(session: Session, state: dict) -> None:
    folds_mod.kv_put(session, HOMESTEAD_STATE, "state", state)


def multiplier(session: Session) -> float:
    """The permanent homestead-XP multiplier from reached milestone tiers.
    Applies to HOMESTEAD XP only — boss/other XP is out of scope (assert)."""
    return 1.0 + MULT_STEP * len(_state(session)["tiers"])


def weekly_reveal(
    db: Session, user: UserInDB, as_of: date, *, recent_accrual_cents: int,
    strain_mode: bool = False,
) -> Optional[WeeklyReveal]:
    """Build the weekly reveal. Under strain mode the reveal is suppressed
    entirely (zero asks). The accrual line is omitted below the trivial-sum floor."""
    if strain_mode:
        return None

    # Projection hero: conservative — extend the real recent accrual linearly to a
    # near horizon. (The What-If commit handles the actual add via propose→confirm.)
    from server.src.services.spend_service import SpendService

    sts = SpendService(db).safe_to_spend(user, as_of=as_of)
    from ...money import dollars_to_cents

    current = dollars_to_cents(sts["breakdown"]["current_balance"])
    horizon_cents = current + recent_accrual_cents * 12  # ~a year at recent pace

    action = {
        "kind": "what_if_commit",
        "label": "Add $25/mo?",
        "deep_link": "/forecast?commit=25",
    }
    accrual_line = recent_accrual_cents if recent_accrual_cents >= TRIVIAL_SUM_CENTS else None
    return WeeklyReveal(
        projection_date=date(as_of.year + 1, as_of.month, 1).isoformat(),
        projection_cents=horizon_cents,
        commit_action=action,
        accrual_line_cents=accrual_line,
    )


def reveal_to_payload(reveal: Optional[WeeklyReveal]) -> dict:
    """Serialize the reveal. The accrual key is ABSENT when suppressed (the test
    asserts key-absence, not a "$0.04" string)."""
    if reveal is None:
        return {"suppressed": True}
    payload = {
        "projection_date": reveal.projection_date,
        "projection_cents": reveal.projection_cents,
        "action": reveal.commit_action,
    }
    if reveal.accrual_line_cents is not None:
        payload["accrual_cents"] = reveal.accrual_line_cents
    return payload


def check_milestones(
    db: Session, user: UserInDB, as_of: date
) -> list[str]:
    """Engine-computed milestone crossings → MilestoneReached (idempotent per
    tier, ratchet). Returns newly-reached tier keys. Multiplier scope: homestead
    XP only."""
    from .stats import StatsService
    from server.src.services.spend_service import SpendService
    from ...money import dollars_to_cents

    state = _state(db)
    reached = set(state["tiers"])
    newly: list[str] = []

    sts = SpendService(db).safe_to_spend(user, as_of=as_of)
    buffer_cents = dollars_to_cents(sts["breakdown"]["current_balance"])
    runway_months, _ = StatsService(db).vitality(user.id, as_of)

    crossings = {
        "buffer_500": buffer_cents >= 50000,
        "runway_1mo": runway_months >= 1.0,
        "runway_3mo": runway_months >= 3.0,
    }
    for key, _cents, _label in MILESTONES:
        if crossings.get(key) and key not in reached:
            reached.add(key)
            newly.append(key)
            record_events(db, [GameEventDraft(
                stream="player", type="MilestoneReached",
                payload={"milestone": key},
                idempotency_key=f"milestone:{user.id}:{key}")])
    if newly:
        # Ratchet: tiers only grow. Order by the canonical milestone order.
        state["tiers"] = [k for k, _c, _l in MILESTONES if k in reached]
        _put(db, state)
        db.flush()
    return newly


def register_homestead_folds() -> None:
    """Homestead has no event-driven projection beyond the milestone ratchet,
    which is written directly by check_milestones; nothing to register as a fold.
    Kept for symmetry with the other modules' registration hooks."""
    return
