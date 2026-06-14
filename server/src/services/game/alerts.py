"""The alert engine (v4 §5.1) — just-in-time, protective, capped.

The FCA's >1M-user result: early *passive* warnings underperform. So alerts
here fire at the **action moment**, not days early, and only for protective /
saving actions — never to suggest spending. Every alert carries a one-tap *fix*
that routes through the existing propose→confirm token pattern; the fix is an
in-app action only (this app is read-only over bank data and NEVER moves real
money between banks).

Triggers (deterministic, evaluated on data refresh + a daily job):
  - BILL_DIP      a known recurring bill due within K=3 days AND projected
                  balance at the due date < buffer floor.
  - NEGATIVE_AHEAD project_cashflows shows a negative balance within 5 days.
  - PAYDAY_SWEEP  income posted today AND an active goal is underfunded → offer
                  a pre-commitment allocation.
  - GRADUATION    sustained underspend / repeated manual allocation (emitted by
                  graduation.py, delivered here under the same caps).

Hygiene (Law 3): ≤1 delivered/day, ≤4/rolling-7-days, per-(type,entity,date)
dedupe, a one-tap "fewer alerts" control. Copy flows through the term catalog —
the *logic* is identical across modes; only vocabulary changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import (
    Account as AccountORM,
    Goal as GoalORM,
    Income as IncomeORM,
)
from ...models import UserInDB
from ...money import dollars_to_cents
from ..recurring_service import RecurringService
from ..spend_service import SpendService
from .events import GameEventDraft, record_events, register_event_type

logger = logging.getLogger(__name__)

# Register the event types this package owns (idempotent at import time).
register_event_type("AlertFired", 1)
register_event_type("AlertFixApplied", 1)
register_event_type("WhatIfCommitted", 1)

# Action-window constants — the FCA lesson, encoded as numbers.
BILL_DIP_WINDOW_DAYS = 3
NEGATIVE_AHEAD_WINDOW_DAYS = 5

# Caps (Law 3).
MAX_PER_DAY = 1
MAX_PER_WEEK = 4

# Severity ordering for the "one per day, highest severity wins" rule.
_SEVERITY = {
    "NEGATIVE_AHEAD": 4,
    "BILL_DIP": 3,
    "GRADUATION": 2,
    "PAYDAY_SWEEP": 1,
}

# Term keys for each alert type's title/body. The plain (off) copy lives in the
# catalog; full mode flavors it. The catalog parity test forces all three files
# to define these keys.
ALERT_TERMS = {
    "BILL_DIP": ("alert.bill_dip.title", "alert.bill_dip.body"),
    "NEGATIVE_AHEAD": ("alert.negative_ahead.title", "alert.negative_ahead.body"),
    "PAYDAY_SWEEP": ("alert.payday_sweep.title", "alert.payday_sweep.body"),
    "GRADUATION": ("alert.graduation.title", "alert.graduation.body"),
}

# Banned substrings in any alert TEMPLATE — alerts must never nudge spending.
BANNED_PATTERNS = ("buy", "spend", "deal", "offer", "discount", "sale")


def idem_key(*, kind: str, entity: str) -> str:
    """The single alert idempotency-key shape: ``alert:<kind>:<entity>``.

    The *period* (if any) is encoded IN ``entity`` by the caller — bills/goals
    already carry their period in entity ("Rent:2026-06-05", "goal:5"), and the
    balance alert now carries it too ("balance:2026-W24"). This builder never
    appends ``fires_at``: doing so would make EVERY key (bills included) change
    daily and re-fire every evening. Keeping the period in ``entity`` is exactly
    how the periodless-balance bug is fixed without regressing the bill key.
    """
    return f"alert:{kind}:{entity}"


def _period_key(as_of: date) -> str:
    """The evaluation period stamped into a periodless alert's entity. ISO
    year-week (e.g. ``2026-W24``): a negative-ahead warning de-dupes within the
    week it was raised but re-fires in the next week if the dip is still ahead —
    matching how a bill's due-date period works, without the every-evening
    re-fire a daily stamp would cause."""
    iso = as_of.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


@dataclass
class Fix:
    """The one-tap action attached to an alert. ``kind`` ∈ {create_allocation,
    create_rule, adjust_earmark, checklist}. Routed through propose→confirm."""

    kind: str
    params: dict[str, Any]
    label: str


@dataclass
class Alert:
    type: str
    fires_at: str  # ISO date
    expires_at: str  # ISO date
    entity: str  # for the idempotency key (bill title, goal id, "balance")
    severity: int
    fix: Optional[Fix] = None
    context: dict[str, Any] = field(default_factory=dict)

    def idempotency_key(self) -> str:
        # Deliberately EXCLUDES fires_at (= the evaluation day). The key must be
        # stable across daily re-evaluations of the same underlying alert, or the
        # same bill re-fires every evening. The entity already carries the
        # distinguishing detail (e.g. "Rent:2026-06-05" — the due date), so a
        # genuinely new occurrence (next month's rent) still gets a fresh key.
        #
        # Step 09: the FIX for the periodless-balance bug lives in the *entity*,
        # not here — the balance alert now sets entity="balance:<period>" so its
        # key changes across periods. This function is unchanged so the BILL key
        # (entity already = "title:date") is byte-identical before and after the
        # step (regression-guarded by test_bill_alert_key_unchanged). Appending
        # fires_at HERE would make the bill key change daily — the every-evening
        # re-fire the :105 comment warns against. Don't.
        return idem_key(kind=self.type, entity=self.entity)


class AlertEngine:
    """Evaluates triggers and (optionally) delivers + records alerts."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.recurring = RecurringService(db)
        self.spend = SpendService(db)

    # ── trigger evaluation (pure: returns candidate alerts, writes nothing) ──

    def evaluate(self, user: UserInDB, as_of: Optional[date] = None) -> list[Alert]:
        """All eligible alerts for *user* as of *as_of*, before caps/dedupe.

        Deterministic and side-effect-free — safe to call repeatedly.
        """
        as_of = as_of or date.today()
        # Package 10 hardening (the Plaid-stale drill): an open sync gap means
        # balances are stale — an alert computed from stale data is noise at
        # best and a false alarm at worst. Fog everywhere: zero alerts until
        # the gap closes (the same pro-player GRAY logic as day verdicts).
        if self._in_open_sync_gap(user):
            return []
        alerts: list[Alert] = []
        alerts.extend(self._bill_dip(user, as_of))
        alerts.extend(self._negative_ahead(user, as_of))
        alerts.extend(self._payday_sweep(user, as_of))
        # Sort by severity desc so callers can take the top one.
        alerts.sort(key=lambda a: a.severity, reverse=True)
        return alerts

    def _in_open_sync_gap(self, user: UserInDB) -> bool:
        """Whether any of the user's accounts sits in an open sync gap."""
        from sqlalchemy import select as _select

        from ...db.models import Account as _AccountORM
        from . import folds as folds_mod

        acct_ids = list(self.db.execute(
            _select(_AccountORM.id).where(_AccountORM.user_id == user.id)
        ).scalars())
        gaps = folds_mod.kv_get(self.db, folds_mod.SYNC_STATE, "gaps") or {"open": []}
        return any(g.get("account_id") in acct_ids for g in gaps.get("open", []))

    def _buffer_floor_cents(self, user: UserInDB) -> int:
        """The user's safety buffer in cents (the bill-dip floor)."""
        s2s = self.spend.safe_to_spend(user, include_outlook=False)
        return dollars_to_cents(s2s["config"]["buffer"])

    def _bill_dip(self, user: UserInDB, as_of: date) -> list[Alert]:
        """A recurring bill due within K days while the projected balance at the
        due date sits below the buffer floor."""
        window_end = as_of + timedelta(days=BILL_DIP_WINDOW_DAYS)
        floor = self._buffer_floor_cents(user)
        out: list[Alert] = []
        flows = self.recurring.project_cashflows(user.id, as_of, window_end)
        # Running balance from current total.
        balance = self.spend.safe_to_spend(user, include_outlook=False)["breakdown"]["current_balance"]
        balance_cents = dollars_to_cents(balance)
        # Walk flows in date order, tracking the balance at each due bill.
        running = balance_cents
        for item in sorted(flows, key=lambda i: i["date"]):
            cents = dollars_to_cents(item["amount"])
            if item["type"] == "income":
                running += cents
                continue
            # An expense (bill). Does paying it dip below the floor?
            running -= cents
            if running < floor:
                out.append(
                    Alert(
                        type="BILL_DIP",
                        fires_at=as_of.isoformat(),
                        expires_at=item["date"],
                        entity=f"{item['title']}:{item['date']}",
                        severity=_SEVERITY["BILL_DIP"],
                        fix=Fix(
                            kind="adjust_earmark",
                            params={"shortfall_cents": floor - running},
                            label="protect_buffer",
                        ),
                        context={"bill": item["title"], "due": item["date"]},
                    )
                )
        return out

    def _negative_ahead(self, user: UserInDB, as_of: date) -> list[Alert]:
        """The projected balance goes negative within the action window."""
        window_end = as_of + timedelta(days=NEGATIVE_AHEAD_WINDOW_DAYS)
        balance = self.spend.safe_to_spend(user, include_outlook=False)["breakdown"]["current_balance"]
        running = dollars_to_cents(balance)
        flows = self.recurring.project_cashflows(user.id, as_of, window_end)
        for item in sorted(flows, key=lambda i: i["date"]):
            cents = dollars_to_cents(item["amount"])
            running += cents if item["type"] == "income" else -cents
            if running < 0:
                return [
                    Alert(
                        type="NEGATIVE_AHEAD",
                        fires_at=as_of.isoformat(),
                        expires_at=item["date"],
                        # Step 09 fix: the balance entity was periodless
                        # ("balance"), so its idempotency key never changed and
                        # the negative-ahead alert fired ONCE per DB lifetime.
                        # Carry the evaluation period in the entity (matching how
                        # bills/goals already do it) so it re-fires next period.
                        entity=f"balance:{_period_key(as_of)}",
                        severity=_SEVERITY["NEGATIVE_AHEAD"],
                        fix=Fix(
                            kind="checklist",
                            params={"shortfall_cents": -running},
                            label="cover_shortfall",
                        ),
                        context={"negative_on": item["date"]},
                    )
                ]
        return []

    def _payday_sweep(self, user: UserInDB, as_of: date) -> list[Alert]:
        """Income posted today AND an active goal is underfunded → offer a
        pre-commitment allocation (behavioral-moat F3).

        'Posted today' means a REAL Income row dated *as_of* — not a projected
        recurring occurrence. project_cashflows(as_of, as_of) returns only future
        projected instances (project_occurrences excludes the anchor and yields
        dates strictly after it), so it can never see the paycheck that actually
        landed today; the trigger has to read the posted row directly.
        """
        income_today = self.db.execute(
            select(IncomeORM.id)
            .join(AccountORM, IncomeORM.account_id == AccountORM.id)
            .where(
                AccountORM.user_id == user.id,
                IncomeORM.date == as_of.isoformat(),
            )
            .limit(1)
        ).first()
        if income_today is None:
            return []
        goal = self.db.execute(
            select(GoalORM)
            .where(GoalORM.user_id == user.id, GoalORM.completed == 0)
            .order_by(GoalORM.date)
            .limit(1)
        ).scalar_one_or_none()
        if goal is None or (goal.progress or 0) >= goal.amount:
            return []
        return [
            Alert(
                type="PAYDAY_SWEEP",
                fires_at=as_of.isoformat(),
                expires_at=(as_of + timedelta(days=2)).isoformat(),
                entity=f"goal:{goal.id}",
                severity=_SEVERITY["PAYDAY_SWEEP"],
                fix=Fix(
                    kind="create_allocation",
                    params={"goal_id": goal.id, "amount": 25.0},
                    label="pre_commit_to_goal",
                ),
                context={"goal": goal.name},
            )
        ]

    # ── caps + delivery (records AlertFired; optionally delivers) ────────────

    def deliver(
        self,
        user: UserInDB,
        as_of: Optional[date] = None,
        *,
        opted_out_types: Optional[set[str]] = None,
        globally_opted_out: bool = False,
    ) -> list[Alert]:
        """Evaluate, apply caps, record ``AlertFired`` for the chosen alert(s),
        and return the delivered alerts.

        Records ``AlertFired`` with ``delivered=false`` for opted-out alerts
        (E8 instrumentation) but does not surface them. Respects the ≤1/day and
        ≤4/week caps using the existing AlertFired event history.
        """
        as_of = as_of or date.today()
        opted_out_types = opted_out_types or set()

        candidates = self.evaluate(user, as_of)
        if not candidates:
            return []

        # Weekly cap: count AlertFired(delivered=true) in the last 7 days.
        delivered_this_week = self._delivered_count(
            user, as_of - timedelta(days=6), as_of
        )
        delivered_today = self._delivered_count(user, as_of, as_of)

        delivered: list[Alert] = []
        for alert in candidates:  # already severity-sorted desc
            suppressed = (
                globally_opted_out or alert.type in opted_out_types
            )
            would_exceed = (
                delivered_today + len(delivered) >= MAX_PER_DAY
                or delivered_this_week + len(delivered) >= MAX_PER_WEEK
            )
            # Always record the firing (idempotent); delivered flag reflects
            # caps + opt-out so instrumentation sees every eligible trigger.
            will_deliver = not suppressed and not would_exceed
            recorded = self._record_fired(user, alert, delivered=will_deliver)
            if recorded and will_deliver:
                delivered.append(alert)
        return delivered

    def _delivered_count(self, user: UserInDB, start: date, end: date) -> int:
        from ...db.models import GameEvent
        import json

        rows = self.db.execute(
            select(GameEvent.payload).where(
                GameEvent.type == "AlertFired",
                GameEvent.stream == f"user:{user.id}",
            )
        ).scalars().all()
        count = 0
        for raw in rows:
            p = json.loads(raw)
            if not p.get("delivered"):
                continue
            fired = p.get("fires_at")
            if fired and start.isoformat() <= fired <= end.isoformat():
                count += 1
        return count

    def _record_fired(
        self, user: UserInDB, alert: Alert, *, delivered: bool
    ) -> bool:
        """Append an idempotent ``AlertFired`` event. Returns True if newly
        inserted, False on an idempotency-key collision (= already fired today,
        so the per-(type,entity,date) dedupe holds)."""
        from ...db.models import GameEvent

        key = alert.idempotency_key()
        already = self.db.execute(
            select(GameEvent.id).where(GameEvent.idempotency_key == key)
        ).scalar_one_or_none()
        if already is not None:
            return False  # dedupe: this exact alert already fired

        draft = GameEventDraft(
            stream=f"user:{user.id}",
            type="AlertFired",
            payload={
                "alert_type": alert.type,
                "entity": alert.entity,
                "fires_at": alert.fires_at,
                "expires_at": alert.expires_at,
                "delivered": delivered,
                "fix_kind": alert.fix.kind if alert.fix else None,
            },
            idempotency_key=key,
        )
        record_events(self.db, [draft])
        return True


def scan_templates_for_banned_patterns(terms: dict[str, str]) -> list[str]:
    """Return alert-template values (from a term catalog) that contain a banned
    spending word. Used by the guardrail test."""
    offenders = []
    for key, value in terms.items():
        if not key.startswith("alert."):
            continue
        low = value.lower()
        if any(bad in low for bad in BANNED_PATTERNS):
            offenders.append(key)
    return offenders
