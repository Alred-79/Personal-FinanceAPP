"""Graduation / fade — the game quiets when a metric stabilizes (v4 §9.4).

After ~8-10 consecutive stable weeks on a metric (e.g. dining at/under its
baseline pace), the game layer for that metric drops to a weekly-summary
altitude: its quests/monsters/alerts stop spawning. DAU going down on a
graduated metric is the north star WINNING — the habit holds without the
scaffolding. A resurface trigger (2 consecutive regressed weeks) restores the
metric quietly; the user can pin a metric in either direction (autonomy both
ways).

Fade NEVER touches the Money Spine: package-03 alerts (5.1 stays default-on —
it's the product), the glanceable number, and Grace are exempt by construction —
nothing in this module is consulted by those paths.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    MetricFade,
)
from ...models import UserInDB
from .events import GameEventDraft, record_events, register_event_type

for _t in ("MetricGraduated", "MetricResurfaced"):
    register_event_type(_t, 1)

# 8-10 weeks is the stability band the spec names; we graduate at the band's
# floor so a 9-stable-week run is already quiet (the cost of being late is
# nagging a user who's already stable — worse than being a week early).
STABLE_WEEKS_TO_GRADUATE = 8
REGRESSED_WEEKS_TO_RESURFACE = 2


def _fade_row(db: Session, user_id: int, metric: str) -> MetricFade:
    row = db.execute(
        select(MetricFade).where(
            MetricFade.user_id == user_id, MetricFade.metric == metric
        )
    ).scalar_one_or_none()
    if row is None:
        row = MetricFade(user_id=user_id, metric=metric)
        db.add(row)
        db.flush()
    return row


def is_faded(db: Session, user: UserInDB, metric: str) -> bool:
    """Whether the game layer is quiet for *metric*. Consulted by monster /
    quest / challenge SPAWNING only — never by spine alerts, the number, or
    Grace (fade exemption is structural: those paths don't import this)."""
    row = db.execute(
        select(MetricFade).where(
            MetricFade.user_id == user.id, MetricFade.metric == metric
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    if row.pin == "always_active":
        return False
    if row.pin == "always_faded":
        return True
    return row.state == "graduated"


def graduated_metrics(db: Session, user: UserInDB) -> list[str]:
    """The metrics currently at weekly-summary altitude (for the summary)."""
    rows = db.execute(
        select(MetricFade).where(MetricFade.user_id == user.id)
    ).scalars().all()
    return sorted(
        r.metric for r in rows
        if (r.state == "graduated" and r.pin != "always_active")
        or r.pin == "always_faded"
    )


class FadeService:
    """The per-metric stability detector + state machine."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── stability measurement (posted spend vs baseline pace) ──────────────

    def week_is_stable(self, user: UserInDB, metric: str, week_end: date) -> Optional[bool]:
        """Whether the week ending *week_end* was at/under baseline pace for
        *metric*. None when the baseline is low-confidence (an unjudgeable
        week counts as neither stable nor regressed — GRAY logic)."""
        from .baselines import category_baseline

        base = category_baseline(self.db, user.id, metric, week_end)
        if base.low_confidence or base.monthly_cents <= 0:
            return None
        weekly_pace = base.monthly_cents * 7 // 30
        week_start = week_end - timedelta(days=6)
        acct_ids = list(self.db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user.id)
        ).scalars())
        if not acct_ids:
            return None
        from sqlalchemy import func

        spent = self.db.execute(
            select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(
                ExpenseORM.account_id.in_(acct_ids),
                ExpenseORM.category == metric,
                ExpenseORM.date >= week_start.isoformat(),
                ExpenseORM.date <= week_end.isoformat(),
            )
        ).scalar_one()
        return int(spent or 0) <= weekly_pace

    # ── the state machine ───────────────────────────────────────────────────

    def note_week(
        self, user: UserInDB, metric: str, week_end: date, stable: Optional[bool]
    ) -> str:
        """Fold one judged week into the fade state. Returns the state after.

        ``stable=None`` (unjudgeable) leaves both counters untouched — a fog
        week neither builds toward graduation nor toward resurfacing.
        """
        row = _fade_row(self.db, user.id, metric)
        if stable is None:
            return row.state
        if stable:
            row.stable_weeks += 1
            row.regressed_weeks = 0
        else:
            row.regressed_weeks += 1
            row.stable_weeks = 0
        # Pins override transitions in BOTH directions; counters keep tracking
        # so unpinning lands in the right state on the next judged week.
        if row.pin == "none":
            if (
                row.state == "active"
                and row.stable_weeks >= STABLE_WEEKS_TO_GRADUATE
            ):
                self._graduate(user, row, week_end)
            elif (
                row.state == "graduated"
                and row.regressed_weeks >= REGRESSED_WEEKS_TO_RESURFACE
            ):
                self._resurface(user, row, week_end)
        self.db.flush()
        return row.state

    def evaluate_week(self, user: UserInDB, metric: str, week_end: date) -> str:
        """Measure + fold one week (the weekly job's per-metric step)."""
        return self.note_week(
            user, metric, week_end, self.week_is_stable(user, metric, week_end)
        )

    def _graduate(self, user: UserInDB, row: MetricFade, week_end: date) -> None:
        row.state = "graduated"
        row.graduated_on = week_end.isoformat()
        record_events(self.db, [GameEventDraft(
            stream="player", type="MetricGraduated",
            payload={"metric": row.metric, "date": week_end.isoformat()},
            idempotency_key=f"fade_grad:{user.id}:{row.metric}:{week_end.isoformat()}",
        )])

    def _resurface(self, user: UserInDB, row: MetricFade, week_end: date) -> None:
        row.state = "active"
        row.graduated_on = None
        row.stable_weeks = 0
        record_events(self.db, [GameEventDraft(
            stream="player", type="MetricResurfaced",
            payload={"metric": row.metric, "date": week_end.isoformat()},
            idempotency_key=f"fade_resurf:{user.id}:{row.metric}:{week_end.isoformat()}",
        )])

    # ── the user pin (autonomy both directions) ─────────────────────────────

    def set_pin(self, user: UserInDB, metric: str, pin: str) -> None:
        if pin not in ("none", "always_active", "always_faded"):
            raise ValueError(f"unknown pin: {pin!r}")
        row = _fade_row(self.db, user.id, metric)
        row.pin = pin
        self.db.flush()

    # ── the weekly-summary surface ──────────────────────────────────────────

    def weekly_summary(self, user: UserInDB) -> dict:
        """Graduated metrics for the weekly summary — the ONE remaining surface
        a graduated metric appears on."""
        return {"graduated_metrics": graduated_metrics(self.db, user)}
