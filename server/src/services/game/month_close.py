"""The month-close job — MonthSealed wiring (deferred from 08/09 to here).

One idempotent entry point, ``close_month``, run when a month ends:

1. gather the month's day verdicts from the event log (dates are stripped to
   verdicts before scoring — package 08's structural no-timing-bonus law),
2. seal the expedition run (score + prestige, idempotent),
3. resolve Heat contracts — met/unmet from VERIFIED posted spend; the sweep
   arm yields a propose→confirm sweep PROPOSAL capped at verified underspend
   (never a direct money move); a killed heat feature voids contracts with a
   soft landing (no penalty),
4. emit ``MonthSealed`` (idempotent), carrying the score summary,
5. update the campaign: quarter rollover (pause, never expire) + milestone
   catch-up (sealed-month milestones derive from the log),
6. write canon facts (streak best) via the engine-only writers.

Kill switches pause a feature's STEP here without breaking anything else —
events keep their meaning; only the feature's job goes quiet.
"""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import GameEvent, HeatContract
from ...models import UserInDB
from .events import GameEventDraft, record_events
from . import experiments


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(x) for x in month.split("-"))
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


def _month_verdicts(db: Session, month: str) -> list[str]:
    """The month's DayClosed verdicts. Only the verdict survives — the scoring
    function never sees dates (no timing bonus, structurally)."""
    start, end = _month_bounds(month)
    rows = db.execute(
        select(GameEvent.payload).where(GameEvent.type == "DayClosed")
    ).scalars().all()
    verdicts = []
    for raw in rows:
        payload = json.loads(raw)
        day = payload.get("date") or ""
        if start.isoformat() <= day <= end.isoformat():
            verdicts.append(payload.get("verdict", "GRAY"))
    return verdicts


def _month_event_count(db: Session, event_type: str, month: str) -> int:
    start, end = _month_bounds(month)
    rows = db.execute(
        select(GameEvent.payload).where(GameEvent.type == event_type)
    ).scalars().all()
    count = 0
    for raw in rows:
        payload = json.loads(raw)
        day = str(payload.get("date") or payload.get("day") or "")
        if start.isoformat() <= day <= end.isoformat():
            count += 1
    return count


def resolve_heat_contracts(
    db: Session, user: UserInDB, month: str, as_of: date
) -> list[dict]:
    """Resolve the month's active Heat contracts. Returns sweep PROPOSALS
    (propose→confirm — this job never moves money and never creates the Rule
    itself). Killed feature → contracts void with a soft landing."""
    from .grace import is_active as grace_is_active
    from .graduation import soft_land
    from .heat import HeatService

    contracts = list(db.execute(
        select(HeatContract).where(
            HeatContract.month == month, HeatContract.status == "active"
        )
    ).scalars())
    proposals: list[dict] = []
    heat = HeatService(db)
    killed = experiments.is_killed("heat")
    for contract in contracts:
        if contract.user_id != user.id:
            continue
        if killed:
            # Feature killed: resolve void + soft landing. No penalty events,
            # nothing deducted; the user never ends below baseline.
            contract.status = "void"
            db.flush()
            soft_land({"amount": 0.0})  # forward-looking copy only
            continue
        verified = heat.verified_underspend_cents(user, contract, as_of)
        met = verified > 0
        contract.status = "met" if met else "unmet"
        db.flush()
        if met and contract.arm == "sweep" and not contract.sweep_paused \
                and not grace_is_active(db):
            base_cap = verified  # min(verified, contracted) — verified IS the cap here
            proposals.append({
                "kind": "heat_sweep",
                "contract_id": contract.id,
                "category": contract.category,
                "amount_cents": heat.sweep_amount_cents(
                    user, contract, base_cap, as_of
                ),
            })
        elif not met:
            heat.soft_land_next_month(contract)  # the smaller re-offer shape
    return proposals


def close_month(
    db: Session, user: UserInDB, month: str, *, as_of: Optional[date] = None
) -> dict:
    """Close *month* for *user*. Idempotent on ``seal:{user}:{month}`` — a
    re-run returns the existing summary and re-does nothing."""
    from .canon import record_streak_best
    from .campaigns import CampaignService, quarter_of
    from .daily import streak_view
    from .expedition import RunService, ScoreInputs

    _, month_end = _month_bounds(month)
    as_of = as_of or month_end

    # Idempotency: a sealed month stays sealed.
    existing = db.execute(
        select(GameEvent).where(
            GameEvent.idempotency_key == f"seal:{user.id}:{month}"
        )
    ).scalar_one_or_none()
    if existing is not None:
        return json.loads(existing.payload).get("score") or {}

    # 1-2. Score + seal the run (skipped while the expedition job is killed —
    # the run rows keep their meaning; sealing resumes when revived).
    score_summary: dict = {}
    if not experiments.is_killed("expedition"):
        inputs = ScoreInputs(
            verdicts=_month_verdicts(db, month),
            objectives_met=0,
            objectives_total=0,
            boss_damage_events=_month_event_count(db, "BossDamaged", month),
            verbs_completed=_month_event_count(db, "ConsistencyVerb", month),
        )
        score_summary = RunService(db).seal(user, month, inputs)

    # 3. Heat resolution (void+soft-land under a kill).
    sweep_proposals = resolve_heat_contracts(db, user, month, as_of)

    # 4. The seal event itself.
    record_events(db, [GameEventDraft(
        stream=f"month:{month}", type="MonthSealed",
        payload={"month": month, "score": score_summary},
        idempotency_key=f"seal:{user.id}:{month}",
    )])
    db.flush()

    # 5. Campaign: quarter rollover (pause, never expire) + log catch-up.
    if not experiments.is_killed("campaigns"):
        campaigns = CampaignService(db)
        quarter = quarter_of(month_end)
        next_day = date(
            month_end.year + (1 if month_end.month == 12 else 0),
            1 if month_end.month == 12 else month_end.month + 1, 1,
        )
        if quarter_of(next_day) != quarter:
            campaigns.close_quarter(user, quarter, as_of)
        campaigns.compute_grants(user, as_of)

    # 6. Canon (engine-only writers; the LLM never writes canon).
    best = streak_view(db).get("best", 0)
    if best:
        record_streak_best(db, user.id, best)

    return {
        "month": month,
        "score": score_summary,
        "sweep_proposals": sweep_proposals,
    }
