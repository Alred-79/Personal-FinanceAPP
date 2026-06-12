"""Habit-monsters — a computed read-model, no schema (v4 §7.1).

Minor monsters and "creepers" are derived on read from finance truth; nothing is
stored. A monster is defeated by verified behaviour (under-budget days / a
cancellation that proves itself when the next expected charge fails to appear),
never by a button.

Rules:
  * discretionary category at >=130% of its baseline monthly pace mid-month
    → a minor monster (essentials NEVER spawn one — a rent spike is not a sin).
  * a subscription with a rising price OR 3+ months without a usage-matched txn
    → a "creeper".
  * at most 2 visible monsters at once (pest avoidance); the worst offenders win.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import (
    Account as AccountORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
)
from ...models import UserInDB

SPAWN_PACE_RATIO = 1.30  # >=130% of baseline pace mid-month spawns a minor monster
UNUSED_MONTHS = 3
MAX_VISIBLE = 2


@dataclass
class HabitMonster:
    kind: str  # "minor" | "creeper"
    key: str  # category name or merchant
    severity: float  # ratio over threshold, for ranking
    reason: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "reason": self.reason}


def _essentials(db: Session) -> set[str]:
    return {
        n
        for n in db.execute(
            select(CategorySettingsORM.name).where(
                CategorySettingsORM.essential == 1
            )
        ).scalars()
    }


def detect_monsters(
    db: Session, user: UserInDB, as_of: Optional[date] = None
) -> list[dict]:
    """Return up to 2 habit-monster dicts, worst first. A pure read."""
    as_of = as_of or date.today()
    essentials = _essentials(db)
    candidates: list[HabitMonster] = []

    # ── minor monsters: discretionary categories off pace ──────────────────
    from server.src.services.budget_service import BudgetService
    from .fade import is_faded

    for summary in BudgetService(db).summarize(user.id, as_of):
        category = summary["category"]
        if category in essentials:
            continue  # essentials never spawn
        if is_faded(db, user, category):
            continue  # graduated metric: the game layer is quiet here (pkg 10)
        target = summary["prorated_target"]
        spent = summary["spent"]
        if target and target > 0 and spent >= SPAWN_PACE_RATIO * target:
            candidates.append(
                HabitMonster(
                    kind="minor",
                    key=category,
                    severity=spent / target,
                    reason="over_pace",
                )
            )

    # ── creepers: rising-price OR long-unused subscriptions ─────────────────
    # NOTE: "unused" by months-since-last-CHARGE never fires for a still-billed
    # subscription (it's charged monthly, so last_date is always recent). Real
    # usage detection needs a usage signal this app doesn't have, so we detect:
    #   (a) a RISING PRICE — the recent charge exceeds an earlier one (a creeping
    #       subscription price hike), computed from the charge history, and
    #   (b) genuinely DORMANT merchants — last charge older than UNUSED_MONTHS
    #       (a cancelled-but-reappearing or paused stream).
    from server.src.services.subscription_service import SubscriptionService

    for sub in SubscriptionService(db).list_subscriptions(user.id, as_of):
        merchant = sub["merchant"]
        last = date.fromisoformat(sub["last_date"]) if sub.get("last_date") else None
        months_since = (
            (as_of.year - last.year) * 12 + (as_of.month - last.month) if last else 0
        )
        rise = _price_rise_ratio(db, user, merchant)
        if rise is not None and rise >= 1.15:  # >=15% price creep
            candidates.append(HabitMonster(
                kind="creeper", key=merchant, severity=1.0 + rise, reason="rising_price"))
        elif months_since >= UNUSED_MONTHS:
            candidates.append(HabitMonster(
                kind="creeper", key=merchant, severity=float(months_since), reason="dormant"))

    # Worst offenders first, capped at 2 (pest avoidance).
    candidates.sort(key=lambda m: m.severity, reverse=True)
    return [m.to_dict() for m in candidates[:MAX_VISIBLE]]


def _price_rise_ratio(db: Session, user: UserInDB, merchant: str) -> Optional[float]:
    """Most-recent charge ÷ earliest charge for *merchant* (normalized), or None
    if there's too little history. >1 means the price crept up over time."""
    from server.src.services.categorization_service import normalize_merchant

    acct_ids = list(db.execute(
        select(AccountORM.id).where(AccountORM.user_id == user.id)
    ).scalars())
    if not acct_ids:
        return None
    rows = db.execute(
        select(ExpenseORM.amount, ExpenseORM.date, ExpenseORM.title).where(
            ExpenseORM.account_id.in_(acct_ids)
        )
    ).all()
    charges = sorted(
        ((d, amt) for amt, d, title in rows
         if normalize_merchant(title or "") == merchant),
        key=lambda c: c[0],
    )
    if len(charges) < 2:
        return None
    first_amt = charges[0][1]
    last_amt = charges[-1][1]
    if first_amt <= 0:
        return None
    return last_amt / first_amt
