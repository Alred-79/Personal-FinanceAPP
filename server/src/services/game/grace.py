"""Basic Grace — deterministic hard-month detection (v4 §6.4 daily clock, §9.1).

Grace is the app quietly easing off when a month is genuinely hard. It is
deterministic (never a model judgment), evaluated daily, and its copy NEVER names
the trigger — "we noticed your income dropped" is banned. Diegetic, neutral
framing only.

Effects (basic; full Grace — boss retreat, capped stacking, opt-out UI — is
package 09):
  * auto-equip a grace ward (allowed beyond the normal cap, marked grace=true),
  * set strain_mode (What-If consumes it; daily copy switches to the strain set),
  * suppress the daily verb except confirm_forecast (the scheduler honours this).

A Grace episode is idempotent: GraceApplied fires once per episode, GraceLifted
on recovery. While Grace is active the day's verdict is GRAY (handled by
DailyService passing grace_active=True).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import UserInDB
from . import folds as folds_mod
from .events import GameEventDraft, record_events, register_event_type

GRACE_STATE = "grace_state"

for _t in ("GraceApplied", "GraceLifted"):
    register_event_type(_t, 1)

# Trigger thresholds.
NEGATIVE_HORIZON_DAYS = 14
INCOME_FLOOR_RATIO = 0.70  # this month's income < 70% of baseline
ESSENTIAL_SHOCK_MULTIPLE = 2.0  # a single essential txn > 2x its category baseline
STS_FLOOR = 0  # Safe-to-Spend below this dollar floor


@dataclass
class GraceSignals:
    will_go_negative: bool
    income_below_floor: bool
    essential_shock: bool
    sts_below_floor: bool

    @property
    def any(self) -> bool:
        return (
            self.will_go_negative
            or self.income_below_floor
            or self.essential_shock
            or self.sts_below_floor
        )


def _grace(session: Session) -> dict:
    return folds_mod.kv_get(session, GRACE_STATE, "state") or {"active": False}


def _grace_put(session: Session, state: dict) -> None:
    folds_mod.kv_put(session, GRACE_STATE, "state", state)


def is_active(session: Session) -> bool:
    return bool(_grace(session).get("active"))


def strain_mode(session: Session) -> bool:
    """What-If (03) consumes this flag; daily copy switches to the strain set."""
    return is_active(session)


class GraceService:
    """Evaluates the deterministic triggers and applies/lifts Grace."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def evaluate(self, user: UserInDB, day: date) -> GraceSignals:
        from .baselines import income_baseline
        from server.src.services.spend_service import SpendService
        from server.src.services.forecast_service import ForecastService

        # 1. will_go_negative within 14 days (forecast lowest balance < 0).
        will_negative = self._will_go_negative(user, day)

        # 2. income this month < 70% of baseline.
        base = income_baseline(self.db, user.id, day)
        month_income = self._month_income_cents(user.id, day)
        income_low = (
            base.monthly_cents > 0
            and not base.low_confidence
            and month_income < INCOME_FLOOR_RATIO * base.monthly_cents
        )

        # 3. essential-category shock: a single essential txn > 2x its baseline.
        shock = self._essential_shock(user, day)

        # 4. Safe-to-Spend below the floor.
        sts = SpendService(self.db).safe_to_spend(user, as_of=day)
        sts_low = float(sts["available"]) < STS_FLOOR

        return GraceSignals(will_negative, income_low, shock, sts_low)

    def apply_if_triggered(self, user: UserInDB, day: date) -> bool:
        """Apply Grace if any trigger fires (idempotent per episode); lift on
        recovery. Returns whether Grace is active after evaluation."""
        signals = self.evaluate(user, day)
        state = _grace(self.db)
        if signals.any and not state.get("active"):
            self._apply(user, day)
            return True
        if not signals.any and state.get("active"):
            self._lift(user, day)
            return False
        return bool(state.get("active"))

    def _apply(self, user: UserInDB, day: date) -> None:
        _grace_put(self.db, {"active": True, "since": day.isoformat()})
        # The grace ward is auto-equipped by the streak_state GraceApplied FOLD
        # (daily._fold_grace_applied), NOT by a direct mutation here — that keeps
        # the grace ward rebuildable from the event log. We only emit the event.
        record_events(self.db, [GameEventDraft(
            stream="player", type="GraceApplied",
            payload={"date": day.isoformat()},
            idempotency_key=f"grace_on:{user.id}:{day.isoformat()}",
        )])
        self.db.flush()

    def _lift(self, user: UserInDB, day: date) -> None:
        _grace_put(self.db, {"active": False, "since": None})
        record_events(self.db, [GameEventDraft(
            stream="player", type="GraceLifted",
            payload={"date": day.isoformat()},
            idempotency_key=f"grace_off:{user.id}:{day.isoformat()}",
        )])
        self.db.flush()

    # ── trigger helpers ───────────────────────────────────────────────────

    def _will_go_negative(self, user: UserInDB, day: date) -> bool:
        from server.src.services.forecast_service import ForecastService

        try:
            fc = ForecastService(self.db).forecast(
                user.id, day, day + timedelta(days=NEGATIVE_HORIZON_DAYS)
            )
        except Exception:
            return False
        return bool(fc.get("will_go_negative"))

    def _month_income_cents(self, user_id: int, day: date) -> int:
        from ...db.models import Income as IncomeORM, Account as AccountORM
        from sqlalchemy import func

        first = date(day.year, day.month, 1)
        acct_ids = list(self.db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user_id)
        ).scalars())
        if not acct_ids:
            return 0
        total = self.db.execute(
            select(func.coalesce(func.sum(IncomeORM.amount), 0)).where(
                IncomeORM.account_id.in_(acct_ids),
                IncomeORM.date >= first.isoformat(),
                IncomeORM.date <= day.isoformat(),
            )
        ).scalar_one()
        return int(total or 0)

    def _essential_shock(self, user: UserInDB, day: date) -> bool:
        from ...db.models import (
            Expense as ExpenseORM,
            Account as AccountORM,
            CategorySettings as CategorySettingsORM,
        )
        from .baselines import category_baseline

        first = date(day.year, day.month, 1)
        essentials = {
            n for n in self.db.execute(
                select(CategorySettingsORM.name).where(
                    CategorySettingsORM.essential == 1
                )
            ).scalars()
        }
        if not essentials:
            return False
        acct_ids = list(self.db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user.id)
        ).scalars())
        if not acct_ids:
            return False
        rows = self.db.execute(
            select(ExpenseORM.amount, ExpenseORM.category).where(
                ExpenseORM.account_id.in_(acct_ids),
                ExpenseORM.category.in_(essentials),
                ExpenseORM.date >= first.isoformat(),
                ExpenseORM.date <= day.isoformat(),
            )
        ).all()
        for amount_cents, category in rows:
            base = category_baseline(self.db, user.id, category, day)
            if base.monthly_cents > 0 and amount_cents > ESSENTIAL_SHOCK_MULTIPLE * base.monthly_cents:
                return True
        return False
