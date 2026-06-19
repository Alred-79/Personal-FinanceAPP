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

# Trigger thresholds (the baseline; widened under neurodivergent_mode — see
# ``grace_params``). These set WHEN Grace eases off; they never change the day's
# verdict machinery, only how readily a hard month is recognised.
NEGATIVE_HORIZON_DAYS = 14
INCOME_FLOOR_RATIO = 0.70  # this month's income < 70% of baseline
ESSENTIAL_SHOCK_MULTIPLE = 2.0  # a single essential txn > 2x its category baseline
STS_FLOOR = 0  # Safe-to-Spend below this dollar floor


@dataclass(frozen=True)
class GraceParams:
    """The deterministic Grace trigger thresholds in effect for an evaluation.

    Pulled out so :data:`neurodivergent_mode` can WIDEN them (detect a hard month
    sooner / more leniently) without changing any verdict logic. Widening is a
    SOFT-LAND: a wider threshold means Grace eases targets earlier — it NEVER
    disables a challenge verdict or voids a streak day. (Challenges are judged by
    :mod:`challenges` from posted events; Grace only sets ``grace_active`` →
    GRAY, which is already the pro-player lenient verdict, never a loss.)
    """

    negative_horizon_days: int = NEGATIVE_HORIZON_DAYS
    income_floor_ratio: float = INCOME_FLOOR_RATIO
    essential_shock_multiple: float = ESSENTIAL_SHOCK_MULTIPLE
    sts_floor: float = STS_FLOOR


def grace_params() -> GraceParams:
    """The Grace thresholds for this run. Baseline by default; WIDENED when
    ``settings.neurodivergent_mode`` is on (B4-gated — off ⇒ identical to today).

    Widening only ever makes Grace MORE generous (a higher income-floor ratio, a
    longer negative horizon, a lower essential-shock multiple), so it can add a
    Grace episode but can NEVER remove one — the soft-land guarantee.
    """
    from server.src.settings import settings

    if not settings.neurodivergent_mode:
        return GraceParams()
    return GraceParams(
        negative_horizon_days=max(
            int(settings.neurodivergent_grace_horizon_days), NEGATIVE_HORIZON_DAYS
        ),
        income_floor_ratio=max(
            float(settings.neurodivergent_grace_income_floor_ratio), INCOME_FLOOR_RATIO
        ),
        essential_shock_multiple=min(
            float(settings.neurodivergent_grace_essential_shock_multiple),
            ESSENTIAL_SHOCK_MULTIPLE,
        ),
        sts_floor=STS_FLOOR,
    )


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

        # The thresholds in effect — baseline, or WIDENED under neurodivergent_mode
        # (B4-gated). Widening only ever eases targets sooner (soft-land); it never
        # voids a verdict.
        params = grace_params()

        # 1. will_go_negative within the (possibly widened) horizon.
        will_negative = self._will_go_negative(user, day, params.negative_horizon_days)

        # 2. income this month < floor-ratio of baseline.
        base = income_baseline(self.db, user.id, day)
        month_income = self._month_income_cents(user.id, day)
        income_low = (
            base.monthly_cents > 0
            and not base.low_confidence
            and month_income < params.income_floor_ratio * base.monthly_cents
        )

        # 3. essential-category shock: a single essential txn > multiple x baseline.
        shock = self._essential_shock(user, day, params.essential_shock_multiple)

        # 4. Safe-to-Spend below the floor.
        sts = SpendService(self.db).safe_to_spend(user, as_of=day, include_outlook=False)
        sts_low = float(sts["available"]) < params.sts_floor

        return GraceSignals(will_negative, income_low, shock, sts_low)

    def apply_if_triggered(
        self, user: UserInDB, day: date, *, opted_out: bool = False
    ) -> bool:
        """Apply Grace if any trigger fires (idempotent per episode); lift on
        recovery. Returns whether Grace is active after evaluation.

        Full Grace (pkg 09):
        * ``opted_out`` ("never ease my targets") → ZERO Grace effects, ever.
        * Capped stacking: multiple triggers in one episode still yield ONE Grace
          level — we record how many triggers fired (for the bestiary/history
          neutral entry) but never intensify beyond a single level.
        """
        if opted_out:
            return False  # honored everywhere — no ward, no strain, no sweep pause
        signals = self.evaluate(user, day)
        state = _grace(self.db)
        if signals.any and not state.get("active"):
            self._apply(user, day, trigger_count=self._count(signals))
            return True
        if not signals.any and state.get("active"):
            self._lift(user, day)
            return False
        return bool(state.get("active"))

    @staticmethod
    def _count(signals: "GraceSignals") -> int:
        return sum([signals.will_go_negative, signals.income_below_floor,
                    signals.essential_shock, signals.sts_below_floor])

    def _apply(self, user: UserInDB, day: date, *, trigger_count: int = 1) -> None:
        # Capped stacking: however many triggers fired, Grace is ONE level. We
        # record the count for the neutral history entry, never to intensify.
        _grace_put(self.db, {
            "active": True, "since": day.isoformat(),
            "level": 1, "trigger_count": max(1, trigger_count),
        })
        # The grace ward is auto-equipped by the streak_state GraceApplied FOLD
        # (daily._fold_grace_applied), NOT by a direct mutation here — that keeps
        # the grace ward rebuildable from the event log. We only emit the event.
        record_events(self.db, [GameEventDraft(
            stream="player", type="GraceApplied",
            payload={"date": day.isoformat(), "triggers": max(1, trigger_count)},
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

    def _will_go_negative(
        self, user: UserInDB, day: date, horizon_days: int = NEGATIVE_HORIZON_DAYS
    ) -> bool:
        from server.src.services.forecast_service import ForecastService

        try:
            # Scheduled-only (include_burn=False): Grace protects against a
            # genuine scheduled shortfall, keeping its trigger independent of the
            # discretionary-burn estimate. ``horizon_days`` is widened under
            # neurodivergent_mode so a slightly-further-out shortfall still eases.
            fc = ForecastService(self.db).forecast(
                user.id, day, day + timedelta(days=horizon_days),
                include_burn=False,
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

    def _essential_shock(
        self, user: UserInDB, day: date,
        shock_multiple: float = ESSENTIAL_SHOCK_MULTIPLE,
    ) -> bool:
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
            if base.monthly_cents > 0 and amount_cents > shock_multiple * base.monthly_cents:
                return True
        return False
