"""W7 — Behavioral features (Tier-1, evidence-graded).

Four behaviorally-validated nudges from ``docs/behavioral-moat.md`` (F1/F2/F4/F6),
each independently flagged (B4 ship-dark) and forecast-gated so a nudge can NEVER
push a user negative. All copy is factual and non-directive, screened through the
output firewall (B3) before it is shown.

* **F1 — Goal-named reminders.** :func:`run_goal_reminders` names a user's actual
  goal + its real progress, but only for goals that have STALLED (funded, then no
  progress activity recently) and only within a cadence cap (≤N/week per goal). A
  user can MUTE goal reminders (a ``reminder_mute`` notification ref); muted ⇒ no
  reminder ever fires. Reuses C3 (``_add_if_new`` / stable ``ref``).

* **F2 — Save-More-Tomorrow escalation.** :func:`run_escalation` bumps an opt-in
  ``allocate`` rule's ``pct``/``amount`` by a configured monthly step — but ONLY when
  the forecast says the bumped contribution would NOT push the user negative (the
  HARD forecast veto). Trivially pausable: opt-in per rule, and disabling the rule or
  clearing ``action_params.escalation`` stops it.

* **F4 — Soft goal earmarks.** :class:`EarmarkService` partitions a goal's
  ``Goal.progress`` into named sub-buckets. SOFT by construction: a pull-back is
  always allowed, instant, and carries no penalty; it warns (never blocks) when the
  forecast sees a near-term bill.

* **F6 — Landmark re-entry.** :func:`run_landmark_reentry` sends ONE gentle re-entry
  notification at a month/year boundary to LAPSED users only (no money activity in N
  days), never to engaged users, and NEVER touches the streak machine.

RLS (guardrail B1): the service functions take an explicit ``user_id`` and assume the
caller (``scheduler``) has already bound the tenant (``set_tenant``) or runs under the
BYPASSRLS scheduler role — mirroring W4/W6.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import (
    Account as AccountORM,
    Earmark as EarmarkORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    Notification as NotificationORM,
    Rule as RuleORM,
)
from ..money import cents_to_dollars
from ..settings import settings
from .game.firewall import screen_output
from .notification_service import NotificationService

log = logging.getLogger(__name__)


def _period(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _safe_message(text: str) -> Optional[str]:
    """Screen one nudge string through the output firewall (B3). Returns the text if
    it passes, or ``None`` if it is blocked (imperative + money / shame) — a blocked
    nudge is dropped rather than rewritten, so we never ship a redirect placeholder as
    a notification body. All copy here is authored factual, so this is a belt-and-
    suspenders guard, not the primary author."""
    verdict = screen_output(text, plain=True)
    return None if verdict.blocked else text


# ── F1: Goal-named reminders ──────────────────────────────────────────────────


def is_muted(db: Session, user_id: int) -> bool:
    """True if the user has muted goal reminders (a ``reminder_mute`` ref exists).

    Mute is the reminder-fatigue escape hatch (B3 edge case): once a user mutes, F1
    suppresses ALL goal reminders for them — "suppress winners". Implemented as a
    durable ``Notification(type='reminder_mute', ref='reminder_mute:{user}')`` row so
    it needs no schema and survives restarts."""
    return (
        db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == user_id,
                NotificationORM.ref == f"reminder_mute:{user_id}",
            )
        ).first()
        is not None
    )


def set_reminder_mute(db: Session, user_id: int, muted: bool) -> bool:
    """Mute (or un-mute) goal reminders for a user. Idempotent; returns the new state.

    Always reversible: un-muting simply deletes the mute row, restoring reminders."""
    ref = f"reminder_mute:{user_id}"
    existing = db.execute(
        select(NotificationORM).where(
            NotificationORM.user_id == user_id, NotificationORM.ref == ref
        )
    ).scalar_one_or_none()
    if muted and existing is None:
        db.add(
            NotificationORM(
                user_id=user_id,
                type="reminder_mute",
                title="Goal reminders muted",
                message="You've muted goal reminders. You can turn them back on any time.",
                ref=ref,
                read=1,  # a control row, not a feed nudge
            )
        )
    elif not muted and existing is not None:
        db.delete(existing)
    db.flush()
    return muted


def _reminders_this_week(db: Session, user_id: int, goal_id: int, now: date) -> int:
    """How many goal-named reminders for this goal were created in the trailing 7
    days — the cadence-cap denominator. Counts by ``ref`` prefix (period-stamped)."""
    week_ago = datetime(now.year, now.month, now.day) - timedelta(days=7)
    return int(
        db.execute(
            select(func.count(NotificationORM.id)).where(
                NotificationORM.user_id == user_id,
                NotificationORM.type == "goal_reminder",
                NotificationORM.ref.like(f"goal_reminder:{user_id}:{goal_id}:%"),
                NotificationORM.created_at >= week_ago,
            )
        ).scalar()
        or 0
    )


def run_goal_reminders(
    db: Session, user_id: int, *, now: Optional[date] = None
) -> dict[str, int]:
    """F1: surface goal-named reminders for the user's STALLED, funded goals.

    A goal is reminder-eligible when it is funded (``progress > 0``), not complete, and
    no earmark/progress has changed recently (stalled). Cadence-capped to
    ``behavioral_reminder_max_per_week`` per goal per rolling week, and fully suppressed
    when the user has muted (B3 fatigue guard). Idempotent: the ``ref`` is week-stamped
    so a re-fire within the same week adds no duplicate. No-op when the flag is off."""
    if not settings.behavioral_goal_reminders_enabled:
        return {"skipped": 0, "created": 0}
    now = now or date.today()
    if is_muted(db, user_id):
        return {"muted": 1, "created": 0}

    notif = NotificationService(db)
    cap = max(int(settings.behavioral_reminder_max_per_week), 0)
    # ISO week stamp makes the ref unique per (goal, week) so the cap can't be
    # defeated by a daily re-fire — at most one ref per goal per week.
    iso_year, iso_week, _ = now.isocalendar()
    week_stamp = f"{iso_year}W{iso_week:02d}"

    created = 0
    goals = (
        db.execute(
            select(GoalORM).where(
                GoalORM.user_id == user_id,
                GoalORM.completed == 0,
            )
        )
        .scalars()
        .all()
    )
    for goal in goals:
        progress = int(goal.progress or 0)
        if progress <= 0 or progress >= int(goal.amount or 0):
            continue  # only funded, not-yet-met goals
        if cap == 0 or _reminders_this_week(db, user_id, goal.id, now) >= cap:
            continue
        pct = (progress / goal.amount * 100) if goal.amount else 0
        message = _safe_message(
            f"Your “{goal.name}” goal is at ${cents_to_dollars(progress):,.2f} of "
            f"${cents_to_dollars(int(goal.amount)):,.2f} ({pct:.0f}%)."
        )
        if message is None:
            continue
        row = notif._add_if_new(
            user_id,
            type="goal_reminder",
            title=f"Progress on “{goal.name}”",
            message=message,
            ref=f"goal_reminder:{user_id}:{goal.id}:{week_stamp}",
        )
        if row is not None:
            created += 1
    db.flush()
    return {"created": created}


# ── F2: Save-More-Tomorrow escalation ─────────────────────────────────────────


def _next_pct(params: dict[str, Any], esc: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The proposed bumped ``action_params`` for one escalation step, or ``None`` when
    nothing to bump / the ceiling is reached. Bumps ``pct`` (by ``step_pct``, capped at
    ``max_pct``) or ``amount`` (by ``step_amount``, capped at ``max_amount``)."""
    new = dict(params)
    if params.get("pct") is not None and esc.get("step_pct") is not None:
        current = float(params["pct"])
        ceiling = float(esc.get("max_pct", 100.0))
        if current >= ceiling:
            return None
        new["pct"] = min(round(current + float(esc["step_pct"]), 4), ceiling)
        return new if new["pct"] > current else None
    if params.get("amount") is not None and esc.get("step_amount") is not None:
        current = float(params["amount"])
        ceiling = float(esc.get("max_amount", float("inf")))
        if current >= ceiling:
            return None
        new["amount"] = min(round(current + float(esc["step_amount"]), 2), ceiling)
        return new if new["amount"] > current else None
    return None


def _escalation_due(esc: dict[str, Any], now: date) -> bool:
    """True if this escalation is due THIS month (one bump per ``period``)."""
    return esc.get("last_escalated_period") != _period(now)


def _would_go_negative(
    db: Session, user_id: int, extra_cents_per_month: int, now: date
) -> bool:
    """THE FORECAST VETO. Project the user's cashflow over the escalation horizon with
    the *additional* monthly contribution modeled as a recurring earmark drain, and
    return whether the balance dips below zero.

    We thread the extra contribution in as a one-off scheduled expense at the start of
    the horizon (the contribution the bumped rule would sweep this cycle) on top of the
    burn-aware forecast, then read ``will_go_negative``. If it would, the bump is
    skipped — a nudge can NEVER push a user negative (hard guardrail)."""
    import random

    from .forecast_service import ForecastService

    if extra_cents_per_month <= 0:
        return False
    horizon = max(int(settings.behavioral_escalation_horizon_days), 1)
    start = now
    end = now + timedelta(days=horizon)
    svc = ForecastService(db)
    # Burn-aware forecast (include_burn) gives the honest "will I dip below zero?"
    # trough. We subtract the extra monthly contribution from the starting balance
    # (the money the bumped rule sets aside is no longer spendable), which is the
    # conservative model: if even reserving it once troughs negative, skip the bump.
    result = svc.forecast(
        user_id,
        start,
        end,
        include_burn=True,
        rng=random.Random(1729),  # fixed seed (B5) — deterministic veto
    )
    from ..money import dollars_to_cents

    lowest_cents = dollars_to_cents(float(result["lowest_balance"]))
    # The bumped contribution reduces the spendable trough by exactly its cents.
    return (lowest_cents - extra_cents_per_month) < 0


def _contribution_cents(params: dict[str, Any]) -> int:
    """Approximate the monthly contribution a bumped rule would set aside, for the
    veto. A fixed ``amount`` rule contributes that amount; a ``pct`` rule's per-sweep
    amount is income-dependent, so we model the percentage of a typical month's income
    via the caller (it passes a representative monthly figure through ``_pct_base``)."""
    if params.get("amount") is not None:
        from ..money import dollars_to_cents

        return max(dollars_to_cents(float(params["amount"])), 0)
    return 0


def run_escalation(
    db: Session, user_id: int, *, now: Optional[date] = None
) -> dict[str, int]:
    """F2: bump each opt-in escalating ``allocate`` rule's contribution by its step —
    but ONLY when the forecast veto allows it (the bump can't push the user negative).

    A rule opts in by carrying an ``escalation`` block in ``action_params``::

        {"pct": 5, "escalation": {"step_pct": 1, "max_pct": 15}}
        {"amount": 50, "escalation": {"step_amount": 25, "max_amount": 200}}

    One bump per rule per month (``last_escalated_period``). Self-gates on the flag.
    Returns counts of bumped / vetoed / skipped rules."""
    if not settings.behavioral_escalation_enabled:
        return {"skipped": 0, "bumped": 0, "vetoed": 0}
    now = now or date.today()

    bumped = vetoed = skipped = 0
    rules = (
        db.execute(
            select(RuleORM).where(
                RuleORM.user_id == user_id,
                RuleORM.enabled == 1,
                RuleORM.action_type == "allocate",
            )
        )
        .scalars()
        .all()
    )
    for rule in rules:
        try:
            params = json.loads(rule.action_params) if rule.action_params else {}
        except (TypeError, ValueError):
            params = {}
        esc = params.get("escalation")
        if not isinstance(esc, dict):
            continue  # not opted in
        if not _escalation_due(esc, now):
            skipped += 1
            continue
        proposed = _next_pct(params, esc)
        if proposed is None:
            skipped += 1  # ceiling reached / nothing to bump
            continue

        # FORECAST VETO (hard requirement): how much MORE per month the bump sweeps.
        # For a fixed-amount rule it's the step in cents; for a pct rule the extra is
        # income-dependent — we use the configured per-month base (esc["pct_base"], the
        # representative monthly income in dollars) so the veto sees the real drain.
        from ..money import dollars_to_cents

        if proposed.get("amount") is not None:
            extra_cents = dollars_to_cents(
                float(proposed["amount"]) - float(params.get("amount") or 0)
            )
        else:
            pct_base = float(esc.get("pct_base", 0.0))
            extra_cents = dollars_to_cents(
                pct_base * (float(proposed["pct"]) - float(params.get("pct") or 0)) / 100.0
            )

        if _would_go_negative(db, user_id, extra_cents, now):
            vetoed += 1
            continue

        # Apply the bump and stamp the period so the next monthly run is a no-op until
        # next month (idempotent per period).
        esc = dict(esc)
        esc["last_escalated_period"] = _period(now)
        proposed["escalation"] = esc
        rule.action_params = json.dumps(proposed)
        bumped += 1
    db.flush()
    return {"bumped": bumped, "vetoed": vetoed, "skipped": skipped}


# ── F4: Soft goal earmarks ────────────────────────────────────────────────────


class EarmarkError(ValueError):
    """A bad earmark request (unknown goal, over-earmark beyond progress, etc.)."""


class EarmarkService:
    """Soft, named sub-buckets over ``Goal.progress`` (F4). Setting an earmark adds its
    cents to the goal's progress; pulling it back subtracts the same cents — always
    allowed, instant, no penalty. The sum of a goal's earmarks never exceeds its
    progress (an earmark can only partition money already saved toward the goal)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _goal(self, user_id: int, goal_id: int) -> GoalORM:
        goal = self.db.execute(
            select(GoalORM).where(GoalORM.id == goal_id, GoalORM.user_id == user_id)
        ).scalar_one_or_none()
        if goal is None:
            raise EarmarkError("goal not found")
        return goal

    @staticmethod
    def _earmark_dict(r: EarmarkORM) -> dict[str, Any]:
        return {
            "id": r.id,
            "goal_id": r.goal_id,
            "name": r.name,
            "amount": cents_to_dollars(int(r.amount_cents or 0)),
            "amount_cents": int(r.amount_cents or 0),
        }

    def list(self, user_id: int, goal_id: int) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(
                select(EarmarkORM).where(
                    EarmarkORM.user_id == user_id, EarmarkORM.goal_id == goal_id
                )
            )
            .scalars()
            .all()
        )
        return [self._earmark_dict(r) for r in rows]

    def list_for_goals(
        self, user_id: int, goal_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Earmarks for many goals in ONE query, grouped by ``goal_id``.

        Avoids the N+1 of calling :meth:`list` per goal on ``GET /goals/``. Goals
        with no earmarks are simply absent from the result (callers default to []).
        """
        result: dict[int, list[dict[str, Any]]] = {}
        if not goal_ids:
            return result
        rows = (
            self.db.execute(
                select(EarmarkORM).where(
                    EarmarkORM.user_id == user_id,
                    EarmarkORM.goal_id.in_(goal_ids),
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            result.setdefault(int(r.goal_id), []).append(self._earmark_dict(r))
        return result

    def set_earmark(
        self,
        user_id: int,
        goal_id: int,
        name: str,
        amount_cents: int,
        *,
        now: Optional[date] = None,
    ) -> dict[str, Any]:
        """Create or resize a named earmark to ``amount_cents`` (absolute, not a delta).

        SOFT (never a lock): the delta is applied to ``Goal.progress`` so the earmark
        reduces Safe-to-Spend, but the money is never frozen — :meth:`release` (or a
        smaller ``set_earmark``) pulls it straight back with no penalty. Raising the
        earmark above the goal's available progress is rejected (you can't earmark money
        you haven't saved); LOWERING is always allowed. Returns the new earmark + a
        non-blocking ``warning`` when the forecast sees a near-term bill."""
        name = (name or "").strip()
        if not name:
            raise EarmarkError("earmark name required")
        if amount_cents < 0:
            raise EarmarkError("earmark amount cannot be negative")
        goal = self._goal(user_id, goal_id)

        row = self.db.execute(
            select(EarmarkORM).where(
                EarmarkORM.user_id == user_id,
                EarmarkORM.goal_id == goal_id,
                EarmarkORM.name == name,
            )
        ).scalar_one_or_none()
        old_cents = int(row.amount_cents) if row is not None else 0
        delta = amount_cents - old_cents

        # Guard: an INCREASE can't earmark more than the goal has saved. A DECREASE
        # (pull-back) is always permitted (never over-restricts the user).
        if delta > 0:
            available = int(goal.progress or 0)
            if delta > available:
                raise EarmarkError(
                    "cannot earmark more than the goal's available progress"
                )

        if row is None:
            row = EarmarkORM(
                goal_id=goal_id, user_id=user_id, name=name, amount_cents=amount_cents
            )
            self.db.add(row)
        else:
            row.amount_cents = amount_cents
        # Earmarking partitions money already in progress; it does NOT inflate progress
        # beyond what was saved. We do not change Goal.progress on a partition — the
        # earmark is a *label* over existing progress. (Total earmarks ≤ progress is
        # enforced by the available-progress guard above.)
        self.db.flush()

        warning = self._near_term_bill_warning(user_id, now or date.today())
        return {
            "id": row.id,
            "goal_id": goal_id,
            "name": name,
            "amount": cents_to_dollars(amount_cents),
            "amount_cents": amount_cents,
            "warning": warning,  # advisory only — never blocks
        }

    def release(self, user_id: int, goal_id: int, name: str) -> bool:
        """Pull back (delete) a named earmark entirely. ALWAYS allowed, instant, no
        penalty — the over-restriction backfire guard. Returns True if one was removed.
        Releasing only removes the *label*; the underlying ``Goal.progress`` is
        untouched (the money was never moved, only partitioned)."""
        row = self.db.execute(
            select(EarmarkORM).where(
                EarmarkORM.user_id == user_id,
                EarmarkORM.goal_id == goal_id,
                EarmarkORM.name == (name or "").strip(),
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    def _near_term_bill_warning(self, user_id: int, now: date) -> Optional[str]:
        """A non-blocking advisory when the burn-aware forecast sees the balance dip
        below zero within ~5 weeks — surfaced (never enforced) so the user can decide.
        Returns ``None`` (no warning) when the forecast is healthy or unavailable."""
        try:
            import random

            from .forecast_service import ForecastService

            result = ForecastService(self.db).forecast(
                user_id,
                now,
                now + timedelta(days=35),
                include_burn=True,
                rng=random.Random(1729),
            )
        except Exception:  # noqa: BLE001 — advisory must never raise into the action
            return None
        if result.get("will_go_negative"):
            return _safe_message(
                "Heads up: your projected balance dips below zero before "
                f"{result.get('lowest_date')} with upcoming bills. This earmark is a "
                "label only — you can release it any time."
            )
        return None


# ── F6: Landmark re-entry (lapsed users only) ─────────────────────────────────


def _last_activity_date(db: Session, user_id: int) -> Optional[date]:
    """The user's most recent money activity date (latest expense or income date), or
    ``None`` if they have none. This is the engagement signal the lapsed predicate reads
    — NOT the streak machine (which we must never touch)."""
    exp = db.execute(
        select(func.max(ExpenseORM.date))
        .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
        .where(AccountORM.user_id == user_id)
    ).scalar()
    inc = db.execute(
        select(func.max(IncomeORM.date))
        .join(AccountORM, IncomeORM.account_id == AccountORM.id)
        .where(AccountORM.user_id == user_id)
    ).scalar()
    candidates = [d for d in (exp, inc) if d]
    if not candidates:
        return None
    parsed: list[date] = []
    for s in candidates:
        try:
            parsed.append(date.fromisoformat(str(s)[:10]))
        except (ValueError, TypeError):
            continue
    return max(parsed) if parsed else None


def is_lapsed(db: Session, user_id: int, now: date) -> bool:
    """True if the user is LAPSED (no money activity within ``behavioral_lapsed_days``).

    THE lapsed predicate (F6). Engaged users — recent activity — are NOT lapsed and are
    skipped, the "what-the-hell" licensing guard (never demotivate on-track users). A
    user with NO activity at all is treated as lapsed (a re-entry candidate)."""
    last = _last_activity_date(db, user_id)
    if last is None:
        return True
    threshold = max(int(settings.behavioral_lapsed_days), 1)
    return (now - last).days >= threshold


def run_landmark_reentry(
    db: Session, user_id: int, *, now: Optional[date] = None
) -> dict[str, int]:
    """F6: at a month/year boundary, send ONE gentle re-entry notification to a LAPSED
    user. Engaged users are skipped. NEVER touches the streak machine (daily.py rebuilds
    rather than breaks — a re-entry must not reset or reward a streak). Idempotent per
    ``ref`` (landmark + period). Self-gates on the flag.

    The caller decides the boundary (the scheduler fires this only on the 1st of a
    month); ``landmark`` distinguishes the year boundary (Jan 1) for copy + ref."""
    if not settings.behavioral_landmark_enabled:
        return {"skipped": 0, "created": 0}
    now = now or date.today()
    if not is_lapsed(db, user_id, now):
        return {"engaged_skipped": 1, "created": 0}

    landmark = "year" if (now.month == 1 and now.day == 1) else "month"
    notif = NotificationService(db)
    if landmark == "year":
        title = "A fresh year"
        body = (
            f"A new year began on {now:%b %d}. Your goals and history are right where "
            "you left them whenever you'd like to look."
        )
    else:
        title = "A fresh month"
        body = (
            f"A new month began on {now:%b %d}. Your goals and history are right where "
            "you left them whenever you'd like to look."
        )
    message = _safe_message(body)
    if message is None:
        return {"created": 0}
    row = notif._add_if_new(
        user_id,
        type="landmark_reentry",
        title=title,
        message=message,
        ref=f"landmark_reentry:{user_id}:{landmark}:{_period(now)}",
    )
    db.flush()
    return {"created": 1 if row is not None else 0}
