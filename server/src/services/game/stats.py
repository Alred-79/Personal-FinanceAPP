"""The four stats + the ``player_state`` projection (v4 §6.1).

Stats are OUTPUTS, derived from finance data and the user's own baselines — there
is no character-creation input flow anywhere (R3). Every stat is a ratio or a
bucket, never a raw dollar amount on the sheet (the tap-reveal shows the real
number; the stat itself never does).

  Vitality = runway: liquid balances ÷ trailing-3-mo total monthly spend, in
             months, displayed bucketed.
  Mana     = savings rate vs. own baseline (ratio — improvement scores, not
             wealth).
  Armor    = on-time-bill ratio × discretionary-budget adherence (30d).
             Essential categories NEVER reduce Armor.
  Might    = net-worth delta + debt principal paid, vs. own baseline.

XP accrues into ``player_state`` via a fold over XP-bearing events, routed
through the one-sided clamp and the consistency daily cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import (
    Account as AccountORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
)
from ...models import UserInDB
from .baselines import (
    Baseline,
    _months_back_start,
    _start_of_month,
    savings_rate_baseline,
    total_spend_baseline,
)
from .clamp import clamped_xp_delta
from .xp import CONSISTENCY_DAILY_CAP, level_for_xp, xp_for_event

PLAYER_STATE = "player_state"

# Vitality buckets by runway months. The sheet shows the bucket label, never the
# precise months figure.
VITALITY_BUCKETS = (
    (1.0, "<1 month"),
    (2.0, "1–2 months"),
    (4.0, "2–4 months"),
    (6.0, "4–6 months"),
    (float("inf"), "6+ months"),
)


def vitality_bucket(runway_months: float) -> str:
    for threshold, label in VITALITY_BUCKETS:
        if runway_months < threshold:
            return label
    return VITALITY_BUCKETS[-1][1]


@dataclass
class Stats:
    vitality_bucket: str
    vitality_months: float  # the real number (tap-reveal only)
    mana_ratio: float  # current savings rate / baseline savings rate
    armor_ratio: float  # on-time × adherence, [0, 1]
    might_ratio: float  # net-worth+principal delta vs baseline
    low_confidence: bool

    def to_dict(self) -> dict:
        return {
            "vitality": {
                "bucket": self.vitality_bucket,
                "months": round(self.vitality_months, 1),
            },
            "mana": round(self.mana_ratio, 2),
            "armor": round(self.armor_ratio, 2),
            "might": round(self.might_ratio, 2),
            "low_confidence": self.low_confidence,
        }


class StatsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _liquid_balance_cents(self, user_id: int) -> int:
        return int(
            self.db.execute(
                select(func.coalesce(func.sum(AccountORM.balance), 0)).where(
                    AccountORM.user_id == user_id
                )
            ).scalar()
            or 0
        )

    def _essential_categories(self) -> set[str]:
        rows = self.db.execute(
            select(CategorySettingsORM.name).where(
                CategorySettingsORM.essential == 1
            )
        ).scalars().all()
        return set(rows)

    def vitality(self, user_id: int, as_of: Optional[date] = None) -> tuple[float, Baseline]:
        """Runway in months = liquid balance ÷ monthly total spend baseline."""
        spend = total_spend_baseline(self.db, user_id, as_of)
        balance = self._liquid_balance_cents(user_id)
        if spend.monthly_cents <= 0:
            # No spend baseline → effectively infinite runway; cap for display.
            return (float(VITALITY_BUCKETS[-1][0]), spend)
        return (balance / spend.monthly_cents, spend)

    def mana(self, user_id: int, as_of: Optional[date] = None) -> float:
        """Current savings rate ÷ baseline savings rate. >1 means improving.

        Ratio-based so a low-income improver outscores a high-income flat earner
        (the anti-wealth-ranking property).
        """
        baseline_rate = savings_rate_baseline(self.db, user_id, as_of)
        current_rate = self._current_savings_rate(user_id, as_of)
        if baseline_rate <= 0:
            # No baseline savings → any positive current rate is "improving".
            return 1.0 + current_rate
        return current_rate / baseline_rate

    def _current_savings_rate(self, user_id: int, as_of: Optional[date]) -> float:
        """The CURRENT (in-progress calendar month) savings rate = (income −
        spend) / income for this month so far. This must be measured from the
        current month, NOT reused from the baseline — otherwise Mana is always
        exactly 1.0 (current/baseline = baseline/baseline) and the improvement
        signal is dead."""
        as_of = as_of or date.today()
        acct_ids = list(self.db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user_id)
        ).scalars())
        if not acct_ids:
            return 0.0
        month_start = _start_of_month(as_of)
        from ...db.models import Income as IncomeORM

        income = self.db.execute(
            select(func.coalesce(func.sum(IncomeORM.amount), 0)).where(
                IncomeORM.account_id.in_(acct_ids),
                IncomeORM.date >= month_start.isoformat(),
                IncomeORM.date <= as_of.isoformat(),
            )
        ).scalar_one()
        spend = self.db.execute(
            select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(
                ExpenseORM.account_id.in_(acct_ids),
                ExpenseORM.date >= month_start.isoformat(),
                ExpenseORM.date <= as_of.isoformat(),
            )
        ).scalar_one()
        inc = int(income or 0)
        if inc <= 0:
            return 0.0
        return max(0.0, (inc - int(spend or 0)) / inc)

    def armor(self, user_id: int, as_of: Optional[date] = None) -> float:
        """On-time-bill ratio × discretionary-budget adherence (30 days).

        Essential-category overruns NEVER reduce Armor (a medical bill is not a
        defense failure). With no discretionary signal yet we return a neutral
        1.0 baseline; the essential exclusion is the tested behavior.
        """
        essentials = self._essential_categories()
        as_of = as_of or date.today()
        acct_ids = list(
            self.db.execute(
                select(AccountORM.id).where(AccountORM.user_id == user_id)
            ).scalars()
        )
        if not acct_ids:
            return 1.0
        # Discretionary adherence: this month's discretionary spend vs the
        # discretionary baseline (both EXCLUDE essentials, so an essential
        # overrun — rent, medical — can never lower Armor). Computed directly
        # from non-essential expense rows so the two figures use identical math.
        disc_baseline = self._discretionary_spend(
            essentials, acct_ids, _months_back_start(as_of, 3), _start_of_month(as_of)
        ) // 3
        disc_current = self._discretionary_recent(essentials, acct_ids, as_of)
        if disc_baseline <= 0:
            adherence = 1.0
        else:
            # Adherence: 1.0 when at/under baseline, scaling down as it exceeds.
            adherence = min(1.0, disc_baseline / max(disc_current, 1))
        # Armor = on-time-bill ratio × adherence (spec §6.1). A missed bill must
        # lower Armor; the discretionary half alone never reflected that.
        return self._on_time_ratio(user_id, as_of) * adherence

    def _on_time_ratio(self, user_id: int, as_of: date) -> float:
        """Fraction of recurring bills due in the trailing 30 days that were paid
        on time. Derived from `BillPaidOnTime` events vs the count of recurring
        bills that came due in the window (a bill due with no on-time event is
        not on-time). Returns 1.0 when no bills were due (nothing to fail)."""
        from datetime import timedelta
        from ...db.models import GameEvent

        window_start = (as_of - timedelta(days=30)).isoformat()
        due = self._recurring_bills_due(user_id, as_of - timedelta(days=30), as_of)
        if due == 0:
            return 1.0
        on_time = self.db.execute(
            select(func.count(GameEvent.id)).where(
                GameEvent.type == "BillPaidOnTime",
                GameEvent.created_at >= window_start,
            )
        ).scalar_one()
        return max(0.0, min(1.0, int(on_time or 0) / due))

    def _recurring_bills_due(self, user_id: int, start: date, end: date) -> int:
        """Count recurring-bill occurrences due in [start, end] (essentials and
        non-essentials both — a missed essential bill IS a defense failure, vs
        an essential overSPEND which is not)."""
        from ..recurring_service import RecurringService

        return len(RecurringService(self.db).project_expenses(user_id, start, end))

    def _discretionary_spend(self, essentials, acct_ids, start, end) -> int:
        conditions = [
            ExpenseORM.account_id.in_(acct_ids),
            ExpenseORM.date >= start.isoformat(),
            ExpenseORM.date < end.isoformat(),
        ]
        if essentials:
            conditions.append(ExpenseORM.category.notin_(essentials))
        spend = self.db.execute(
            select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(*conditions)
        ).scalar_one()
        return int(spend or 0)

    def _discretionary_recent(self, essentials, acct_ids, as_of) -> int:
        from datetime import timedelta

        start = (as_of - timedelta(days=30)).isoformat()
        conditions = [
            ExpenseORM.account_id.in_(acct_ids),
            ExpenseORM.date >= start,
            ExpenseORM.date <= as_of.isoformat(),
        ]
        if essentials:
            conditions.append(ExpenseORM.category.notin_(essentials))
        spend = self.db.execute(
            select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(*conditions)
        ).scalar_one()
        return int(spend or 0)

    def might(self, user_id: int, as_of: Optional[date] = None) -> float:
        """Net-worth delta + debt principal paid vs. own baseline.

        Debt principal isn't modeled until package 06, so Might is net-worth
        improvement vs. the spend baseline here — a ratio, never an absolute.
        """
        balance = self._liquid_balance_cents(user_id)
        spend = total_spend_baseline(self.db, user_id, as_of).monthly_cents
        if spend <= 0:
            return 1.0
        # A simple, ratio-shaped proxy: months of buffer relative to one month
        # of spend, normalized so it's improvement-shaped, not wealth-shaped.
        return min(balance / spend, 12.0) / 12.0

    def compute(self, user: UserInDB, as_of: Optional[date] = None) -> Stats:
        runway, spend_baseline = self.vitality(user.id, as_of)
        return Stats(
            vitality_bucket=vitality_bucket(runway),
            vitality_months=runway if runway != float("inf") else 999.0,
            mana_ratio=self.mana(user.id, as_of),
            armor_ratio=self.armor(user.id, as_of),
            might_ratio=self.might(user.id, as_of),
            low_confidence=spend_baseline.low_confidence,
        )


# ── player_state projection: XP + level ──────────────────────────────────


def _player_get(session: Session, key: str) -> dict | None:
    from . import folds as folds_mod

    return folds_mod.kv_get(session, PLAYER_STATE, key)


def _player_put(session: Session, key: str, value: dict) -> None:
    from . import folds as folds_mod

    folds_mod.kv_put(session, PLAYER_STATE, key, value)


def _fold_xp(session: Session, payload: dict, meta) -> None:
    """Accrue XP from an XP-bearing event into player_state.

    Routes the delta through the one-sided clamp (XP never decreases) and the
    consistency daily cap. Forbidden events award nothing (xp_for_event → 0).
    """
    base = xp_for_event(meta.type, payload)
    if base <= 0:
        return

    state = _player_get(session, "xp") or {"xp": 0, "consistency_by_day": {}}

    if meta.type == "ConsistencyVerb":
        # The day MUST come from the payload — a fold is replay-deterministic and
        # can't read wall-clock. Package 05 stamps "day" when it emits the verb.
        day = payload.get("day", "unknown")
        by_day = state.setdefault("consistency_by_day", {})
        spent = by_day.get(day, 0)
        remaining = max(CONSISTENCY_DAILY_CAP - spent, 0)
        grant = min(base, remaining)
        if grant <= 0:
            return
        applied, _true = clamped_xp_delta(grant)
        by_day[day] = spent + applied
    else:
        applied, _true = clamped_xp_delta(base)

    state["xp"] = state.get("xp", 0) + applied
    state["level"] = level_for_xp(state["xp"])
    _player_put(session, "xp", state)


def register_stat_folds() -> None:
    """Register the XP fold for every XP-bearing event type (idempotent)."""
    from . import folds as folds_mod
    from .xp import XP_BEARING

    for event_type in XP_BEARING:
        # Avoid duplicate registration.
        existing = [
            p for (p, _h) in folds_mod.folds_for(event_type) if p == PLAYER_STATE
        ]
        if existing:
            continue
        folds_mod.register_fold(PLAYER_STATE, event_type, _fold_xp)


def player_xp(session: Session) -> dict:
    """Current {xp, level} from the projection (zeros if unseeded)."""
    state = _player_get(session, "xp") or {"xp": 0, "level": 0}
    return {"xp": state.get("xp", 0), "level": state.get("level", 0)}


register_stat_folds()
