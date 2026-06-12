"""The daily skeleton (v4 §6.2 basic, §6.3, §6.4 daily clock, §9.1).

The habit engine — the daily loop, not the monthly spectacle, carries retention.
Everything here folds over the event log into the ``streak_state`` projection, so
it is rebuildable and never reads wall-clock time inside a fold (the day always
comes from the event payload).

Five pieces, all governed by the pro-player rule "when in doubt, GRAY":

* **Green-day verdict** — a closed day is GREEN / GRAY / MISS. GRAY (fog,
  low-confidence, no data, pending-only, Grace active) NEVER breaks a streak.
* **Streak machine** — states ``active | rebuilding | reviving``. There is no
  ``broken`` state *by construction*, so the display contract ("a broken streak
  is never rendered as broken") is structurally unviolable.
* **Wards** — 2 auto-applied reserve slots; a MISS consumes one (post-hoc notice)
  instead of breaking the streak. Replenished only by XP-bearing money actions.
* **Revival** — a dead ≥30-day streak can be re-earned once/quarter via 3 green
  days; GRAY days pause (don't reset) the count.
* **Overnight tick** — small capped XP accrual surfaced as a "collect" affordance.
  Collect reveals the already-accrued amount and awards nothing extra.

Basic Grace (deterministic hard-month detection) lives in :mod:`grace`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import CategorySettings as CategorySettingsORM
from ...models import UserInDB
from . import folds as folds_mod
from .events import GameEventDraft, record_events, register_event_type

STREAK_STATE = "streak_state"

# Verdicts.
GREEN = "GREEN"
GRAY = "GRAY"
MISS = "MISS"

# Streak machine states. NOTE: there is deliberately no "broken" — a lapsed
# streak goes to "rebuilding" (best preserved), so no surface can render "broken".
ACTIVE = "active"
REBUILDING = "rebuilding"
REVIVING = "reviving"

WARD_CAP = 2
WARD_XP_THRESHOLD = 50  # cumulative XP-bearing XP per +1 ward (cap WARD_CAP)
REVIVAL_MIN_BEST = 30
REVIVAL_MAX_DEAD_DAYS = 90
REVIVAL_GREEN_DAYS = 3
TICK_PER_DAY = 1  # XP accrued per verified day, surfaced via collect
TICK_UNCOLLECTED_CAP_DAYS = 7

# Event types this package introduces. Classified in xp.py (UnderBudgetDayClosed
# and ConsistencyVerb are XP-bearing there; the rest are forbidden / neutral).
for _t in (
    "DayClosed",
    "WardConsumed",
    "WardEarned",
    "RevivalOffered",
    "RevivalCompleted",
    "RevivalEnded",
    "TickAccrued",
    "TickCollected",
):
    register_event_type(_t, 1)


@dataclass
class DayInputs:
    """Everything the verdict needs, gathered OUTSIDE the fold (the fold is pure).

    ``safe_to_spend`` is dollars; ``discretionary_over`` is whether any
    discretionary (non-essential) category is over its budget pace; the GRAY
    flags collapse all lenient conditions.
    """

    safe_to_spend: float
    discretionary_over: bool
    has_data: bool
    only_pending: bool
    low_confidence: bool
    in_sync_gap: bool
    grace_active: bool


def verdict_for_day(inp: DayInputs) -> str:
    """The day's verdict from gathered inputs. GRAY wins every tie (pro-player).

    GREEN: discretionary within pace AND Safe-to-Spend >= 0.
    GRAY:  sync gap / low-confidence / no data / pending-only / Grace active.
    MISS:  verifiably over (and none of the GRAY conditions hold).
    """
    # GRAY conditions are sacred — checked first, and any one of them wins.
    if (
        inp.in_sync_gap
        or inp.low_confidence
        or inp.grace_active
        or not inp.has_data
        or inp.only_pending
    ):
        return GRAY
    if inp.discretionary_over or inp.safe_to_spend < 0:
        return MISS
    return GREEN


# ── streak_state projection access ───────────────────────────────────────


def _state(session: Session) -> dict:
    return folds_mod.kv_get(session, STREAK_STATE, "state") or {
        "status": ACTIVE,
        "current": 0,
        "best": 0,
        "wards": 0,
        "grace_wards": 0,
        "last_date": None,
        "dead_on": None,  # date the streak last died (for revival eligibility)
        "revival": None,  # {"green": int, "offered_on": str} when reviving
        "revival_used_quarter": None,
        "xp_for_wards": 0,  # cumulative XP counted toward the next ward
        "closed_days": [],  # idempotency: dates already closed
    }


def _put(session: Session, state: dict) -> None:
    folds_mod.kv_put(session, STREAK_STATE, "state", state)


def _quarter(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


# ── folds ────────────────────────────────────────────────────────────────


def _fold_day_closed(session: Session, payload: dict, meta) -> None:
    """Advance the streak machine for one closed day.

    Pure over (payload, current projection). The day and verdict come from the
    event; nothing here reads the clock or finance tables.
    """
    day = payload.get("date")
    verdict = payload.get("verdict")
    if day is None or verdict not in (GREEN, GRAY, MISS):
        return

    state = _state(session)
    # Idempotent: a day already folded is a no-op (re-run close job is safe).
    if day in state["closed_days"]:
        return
    state["closed_days"].append(day)
    state["last_date"] = day

    # Revival in progress: GREEN advances, GRAY pauses, MISS ends it quietly.
    if state["status"] == REVIVING and state.get("revival"):
        if verdict == GREEN:
            state["revival"]["green"] += 1
            if state["revival"]["green"] >= REVIVAL_GREEN_DAYS:
                state["current"] = state["best"]
                state["status"] = ACTIVE
                state["revival_used_quarter"] = _quarter(_parse(day))
                state["revival"] = None
        elif verdict == MISS:
            # Ends quietly — no penalty event. Mark the quarter consumed so the
            # offer isn't immediately re-made (the once-per-quarter rule applies
            # to the ATTEMPT, not just a success — otherwise offer_revival would
            # re-fire every day the streak stays rebuilding).
            state["status"] = REBUILDING
            state["revival"] = None
            state["revival_used_quarter"] = _quarter(_parse(day))
        _put(session, state)
        return

    if verdict == GRAY:
        _put(session, state)  # GRAY never changes the count
        return

    if verdict == GREEN:
        if state["status"] == REBUILDING:
            # Endowed restart: first GREEN in rebuilding → current = 1 (never 0).
            state["status"] = ACTIVE
            state["current"] = 1
        else:
            state["current"] += 1
        if state["current"] > state["best"]:
            state["best"] = state["current"]
        _put(session, state)
        return

    # verdict == MISS. The fold is PURE: it only updates counts from the prior
    # state. It must NOT emit events (a fold runs on every rebuild — emitting
    # would be impure). The WardConsumed *notice* event is appended by the
    # service layer (close_day), which can observe the count drop; the streak
    # math here depends only on the DayClosed payload and prior state.
    if state["grace_wards"] > 0 or state["wards"] > 0:
        # Consume oldest ward; grace wards first (auto-apply order guardrail).
        if state["grace_wards"] > 0:
            state["grace_wards"] -= 1
        else:
            state["wards"] -= 1
        _put(session, state)
        return

    # No ward: lapse into rebuilding, preserving best. No "broken" state exists.
    if state["current"] > 0:
        state["dead_on"] = day
    state["status"] = REBUILDING
    state["current"] = 0
    _put(session, state)


def _fold_ward_consumed(session: Session, payload: dict, meta) -> None:
    """The post-hoc notice is delivered by the daily service, not the fold; the
    fold only needs to be idempotent (the ward was already decremented)."""
    return


def _fold_ward_earned(session: Session, payload: dict, meta) -> None:
    state = _state(session)
    total = state["wards"] + state["grace_wards"]
    if total < WARD_CAP:
        state["wards"] += 1
    _put(session, state)


def _fold_xp_for_wards(session: Session, payload: dict, meta) -> None:
    """Count XP-bearing events toward the next earned ward (never app-opens)."""
    from .xp import xp_for_event

    gained = xp_for_event(meta.type, payload)
    if gained <= 0:
        return
    state = _state(session)
    state["xp_for_wards"] = state.get("xp_for_wards", 0) + gained
    earned = 0
    while state["xp_for_wards"] >= WARD_XP_THRESHOLD and (
        state["wards"] + state["grace_wards"] + earned
    ) < WARD_CAP:
        state["xp_for_wards"] -= WARD_XP_THRESHOLD
        earned += 1
    # Just add what was earned. The loop guard above already respects the cap
    # (counting grace_wards), so do NOT re-clamp with
    # min(..., WARD_CAP - grace_wards): that would silently destroy a previously
    # earned ward the moment a grace ward is added (e.g. 2 earned + 1 grace, then
    # any XP event recomputes min(2, 2-1)=1, dropping an earned ward).
    state["wards"] = state["wards"] + earned
    _put(session, state)


def _fold_tick_accrued(session: Session, payload: dict, meta) -> None:
    state = _state(session)
    pending = state.get("tick_pending", 0)
    state["tick_pending"] = min(pending + TICK_PER_DAY, TICK_UNCOLLECTED_CAP_DAYS * TICK_PER_DAY)
    _put(session, state)


def _fold_tick_collected(session: Session, payload: dict, meta) -> None:
    state = _state(session)
    state["tick_pending"] = 0
    _put(session, state)


def _fold_revival_offered(session: Session, payload: dict, meta) -> None:
    """Accepting a revival offer transitions rebuilding → reviving. Driven by an
    event so the transition is rebuildable (the fold replays it). The eligibility
    gate is checked by the service BEFORE the event is emitted."""
    state = _state(session)
    if state["status"] != REBUILDING:
        return  # only a rebuilding streak can enter a revival
    state["status"] = REVIVING
    state["revival"] = {"green": 0, "offered_on": payload.get("date")}
    _put(session, state)


def _fold_grace_applied(session: Session, payload: dict, meta) -> None:
    """A Grace episode auto-equips a grace ward beyond the cap. This is a FOLD on
    streak_state so the grace ward is rebuildable — GraceApplied is in the event
    log, so replaying it reproduces the live grace_wards count. (grace.py emits
    the event; it must NOT mutate grace_wards directly, or the live ward would
    vanish on rebuild.)"""
    state = _state(session)
    state["grace_wards"] = state.get("grace_wards", 0) + 1
    _put(session, state)


def _parse(d: str) -> date:
    return date.fromisoformat(d)


def register_daily_folds() -> None:
    """Register every streak_state fold (idempotent)."""
    if any(
        p == STREAK_STATE for ps in folds_mod._FOLDS.values() for p, _ in ps
    ):
        return
    folds_mod.register_fold(STREAK_STATE, "DayClosed", _fold_day_closed)
    folds_mod.register_fold(STREAK_STATE, "WardConsumed", _fold_ward_consumed)
    folds_mod.register_fold(STREAK_STATE, "WardEarned", _fold_ward_earned)
    folds_mod.register_fold(STREAK_STATE, "TickAccrued", _fold_tick_accrued)
    folds_mod.register_fold(STREAK_STATE, "TickCollected", _fold_tick_collected)
    # Grace auto-equips a grace ward; folding GraceApplied keeps it rebuildable.
    folds_mod.register_fold(STREAK_STATE, "GraceApplied", _fold_grace_applied)
    # Accepting a revival offer transitions rebuilding → reviving (rebuildable).
    folds_mod.register_fold(STREAK_STATE, "RevivalOffered", _fold_revival_offered)
    # XP-bearing money actions also feed the ward-replenish counter.
    from .xp import XP_BEARING

    for event_type in XP_BEARING:
        if event_type == "ConsistencyVerb":
            continue  # consistency verbs never replenish wards (probe test)
        folds_mod.register_fold(STREAK_STATE, event_type, _fold_xp_for_wards)


def streak_view(session: Session) -> dict:
    """Read the streak for display. NEVER exposes a 'broken' concept.

    Returns the status, the rendered current/best, ward counts, and the
    collectible tick total. The caller maps these to mode-appropriate copy.
    """
    s = _state(session)
    return {
        "status": s["status"],
        "current": s["current"],
        "best": s["best"],
        "wards": s["wards"],
        "grace_wards": s["grace_wards"],
        "tick_collectible": s.get("tick_pending", 0),
        "reviving": s["status"] == REVIVING,
    }


# ── The daily service: gather inputs, close days, schedule the verb, tick ──

# Daily verbs the scheduler may offer (≤1/day). Skipping any is free, unremarked.
VERB_CONFIRM_FORECAST = "confirm_forecast"
VERB_SCOUT_BILL = "scout_bill"
VERB_WHAT_IF = "what_if"
VERB_WORTH_IT_TAG = "worth_it_tag"


def _in_sync_gap(session: Session, account_ids: list[int]) -> bool:
    gaps = folds_mod.kv_get(session, folds_mod.SYNC_STATE, "gaps") or {"open": []}
    return any(g.get("account_id") in account_ids for g in gaps.get("open", []))


class DailyService:
    """Orchestrates the daily loop. Reads finance truth (never writes it) and
    appends events; the streak math itself lives in the folds above."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── day close ─────────────────────────────────────────────────────────

    def gather_inputs(
        self, user: UserInDB, day: date, *, grace_active: bool = False
    ) -> DayInputs:
        """Collect everything the verdict needs from finance truth (read only).

        A day closes by evaluating *yesterday* (the caller passes the settled
        day). Pending-only and no-data both collapse to GRAY upstream.
        """
        from .baselines import _account_ids, _is_low_confidence

        acct_ids = _account_ids(self.db, user.id)
        low_conf = _is_low_confidence(self.db, user.id, day)
        in_gap = _in_sync_gap(self.db, acct_ids)

        # Discretionary budgets off-pace (essentials excluded — an essential
        # overrun can never MISS a day).
        essentials = {
            n for n in self.db.execute(
                select(CategorySettingsORM.name).where(
                    CategorySettingsORM.essential == 1
                )
            ).scalars()
        }
        from .budget_pace import discretionary_over_pace

        disc_over = discretionary_over_pace(self.db, user, day, essentials)

        from server.src.services.spend_service import SpendService

        sts = SpendService(self.db).safe_to_spend(user, as_of=day)

        has_data = bool(acct_ids) and self._had_activity(acct_ids, day)
        only_pending = False  # pending txns aren't modelled separately yet → False

        return DayInputs(
            safe_to_spend=float(sts["available"]),
            discretionary_over=disc_over,
            has_data=has_data,
            only_pending=only_pending,
            low_confidence=low_conf,
            in_sync_gap=in_gap,
            grace_active=grace_active,
        )

    def _had_activity(self, acct_ids: list[int], day: date) -> bool:
        from ...db.models import Expense as ExpenseORM

        if not acct_ids:
            return False
        row = self.db.execute(
            select(ExpenseORM.id).where(
                ExpenseORM.account_id.in_(acct_ids),
                ExpenseORM.date <= day.isoformat(),
            ).limit(1)
        ).first()
        return row is not None

    def close_day(
        self, user: UserInDB, day: date, *, grace_active: bool = False
    ) -> str:
        """Close *day* for *user*: compute the verdict, emit DayClosed (and, on
        GREEN, the XP-bearing UnderBudgetDayClosed), folding the streak machine.

        Idempotent on ``day:<user>:<date>``. Returns the verdict. Delivers the
        ward post-hoc notice if a ward was consumed by this close.
        """
        inp = self.gather_inputs(user, day, grace_active=grace_active)
        verdict = verdict_for_day(inp)

        wards_before = _state(self.db)["wards"] + _state(self.db)["grace_wards"]

        drafts = [
            GameEventDraft(
                stream="player",
                type="DayClosed",
                payload={"date": day.isoformat(), "verdict": verdict},
                idempotency_key=f"day:{user.id}:{day.isoformat()}",
            )
        ]
        if verdict == GREEN:
            drafts.append(
                GameEventDraft(
                    stream="player",
                    type="UnderBudgetDayClosed",
                    payload={"date": day.isoformat()},
                    idempotency_key=f"green:{user.id}:{day.isoformat()}",
                )
            )
        record_events(self.db, drafts)
        self.db.flush()

        wards_after = _state(self.db)["wards"] + _state(self.db)["grace_wards"]
        if verdict == MISS and wards_after < wards_before:
            # A ward was consumed by the fold. Record the (non-XP) notice event
            # and deliver the post-hoc notification — done HERE, in the service,
            # so the fold stays pure and rebuild-safe.
            record_events(self.db, [GameEventDraft(
                stream="player", type="WardConsumed",
                payload={"date": day.isoformat()},
                idempotency_key=f"ward:{user.id}:{day.isoformat()}",
            )])
            self.db.flush()
            self._notify_ward_held(user, day)

        return verdict

    def _notify_ward_held(self, user: UserInDB, day: date) -> None:
        """Post-hoc, diegetic ward notice — never references spending."""
        from server.src.services.notification_service import NotificationService

        NotificationService(self.db)._add_if_new(
            user.id,
            type="ward_held",
            title="A ward held the line",
            message="A ward held the line last night. Nothing to do.",
            ref=f"ward_held:{user.id}:{day.isoformat()}",
        )

    # ── overnight tick ────────────────────────────────────────────────────

    def accrue_tick(self, user: UserInDB, day: date) -> None:
        """Accrue one capped XP tick for a verified day (XP only, no money)."""
        record_events(self.db, [GameEventDraft(
            stream="player", type="TickAccrued",
            payload={"date": day.isoformat()},
            idempotency_key=f"tick:{user.id}:{day.isoformat()}",
        )])
        self.db.flush()

    def collect_tick(self, user: UserInDB) -> int:
        """Reveal and collect the accrued tick. Awards NOTHING extra — it just
        zeroes the pending counter (collect is presentation)."""
        pending = _state(self.db).get("tick_pending", 0)
        record_events(self.db, [GameEventDraft(
            stream="player", type="TickCollected",
            payload={"amount": pending},
        )])
        self.db.flush()
        return pending

    # ── the daily verb scheduler ──────────────────────────────────────────

    def pick_verb(
        self,
        user: UserInDB,
        day: date,
        *,
        strain_mode: bool = False,
        confidence_dropped: bool = False,
        big_bill_days_out: Optional[int] = None,
        slack_available: bool = False,
    ) -> Optional[str]:
        """Choose ≤1 verb for the day. Under strain, only confirm_forecast.

        Order: forecast-confirm when recurring confidence dropped; scout when a
        big bill is 3-7 days out; what-if when slack exists; tag otherwise.
        Skipping is free; this only *offers*.
        """
        if strain_mode:
            return VERB_CONFIRM_FORECAST
        if confidence_dropped:
            return VERB_CONFIRM_FORECAST
        if big_bill_days_out is not None and 3 <= big_bill_days_out <= 7:
            return VERB_SCOUT_BILL
        if slack_available:
            return VERB_WHAT_IF
        return VERB_WORTH_IT_TAG

    def complete_verb(self, user: UserInDB, day: date, verb: str) -> None:
        """A completed verb emits one capped ConsistencyVerb. Skipped → nothing."""
        record_events(self.db, [GameEventDraft(
            stream="player", type="ConsistencyVerb",
            payload={"day": day.isoformat(), "verb": verb},
            idempotency_key=f"verb:{user.id}:{day.isoformat()}",
        )])
        self.db.flush()

    # ── revival ───────────────────────────────────────────────────────────

    def revival_eligible(self, day: date) -> bool:
        """Whether a dead streak can be revived as of *day* (v4 §6.3 Task 3):
        previous best ≥ 30, dead ≤ 90 days, in `rebuilding`, and not already
        used this quarter. Pure read of streak_state + the given day."""
        s = _state(self.db)
        if s["status"] != REBUILDING:
            return False
        if s["best"] < REVIVAL_MIN_BEST:
            return False
        if not s.get("dead_on"):
            return False
        dead_days = (day - _parse(s["dead_on"])).days
        if dead_days < 0 or dead_days > REVIVAL_MAX_DEAD_DAYS:
            return False
        if s.get("revival_used_quarter") == _quarter(day):
            return False
        return True

    def offer_revival(self, user: UserInDB, day: date) -> bool:
        """Offer + accept a revival if eligible: emits RevivalOffered, which the
        fold turns into a `reviving` transition (3 green days restore `best`).
        Returns whether a revival was started. Idempotent per (user, quarter)."""
        if not self.revival_eligible(day):
            return False
        record_events(self.db, [GameEventDraft(
            stream="player", type="RevivalOffered",
            payload={"date": day.isoformat(), "best": _state(self.db)["best"]},
            idempotency_key=f"revival:{user.id}:{_quarter(day)}",
        )])
        self.db.flush()
        return True
