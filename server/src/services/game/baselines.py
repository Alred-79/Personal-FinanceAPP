"""Per-user baselines (v4 §6.1).

Stats are ratios against the user's OWN trailing-3-calendar-month baselines, not
absolutes — so a user saving $50/mo from a tight income can out-level one
coasting on $2,000/mo (anti-wealth-ranking, anti-shame, and the only fair Heat
input later).

Baselines exclude: pending transactions (not modeled here — expenses/income are
posted rows), transfers between the user's own accounts, and refund-matched
pairs (an expense and an equal-and-opposite income that net to zero). A user
with <6 weeks of data is ``LOW_CONFIDENCE``; consumers must check the flag
(Heat refuses to price against it; stats render a "calibrating" state).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
)
from ...dates import parse_iso_date

# Below this many weeks of history, baselines are flagged low-confidence.
LOW_CONFIDENCE_WEEKS = 6
BASELINE_MONTHS = 3


@dataclass
class Baseline:
    monthly_cents: int
    low_confidence: bool


def _months_back_start(as_of: date, months: int) -> date:
    """First day of the calendar month `months` before *as_of*'s month."""
    m = as_of.month - 1 - months
    year = as_of.year + m // 12
    month = m % 12 + 1
    return date(year, month, 1)


def _start_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def _account_ids(db: Session, user_id: int) -> list[int]:
    return list(
        db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user_id)
        ).scalars()
    )


def _earliest_activity(db: Session, user_id: int) -> Optional[date]:
    acct_ids = _account_ids(db, user_id)
    if not acct_ids:
        return None
    rows = db.execute(
        select(func.min(ExpenseORM.date)).where(
            ExpenseORM.account_id.in_(acct_ids)
        )
    ).scalar_one_or_none()
    return parse_iso_date(rows) if rows else None


def _is_low_confidence(db: Session, user_id: int, as_of: date) -> bool:
    earliest = _earliest_activity(db, user_id)
    if earliest is None:
        return True
    weeks = (as_of - earliest).days / 7
    return weeks < LOW_CONFIDENCE_WEEKS


def _refund_offset_cents(
    db: Session, acct_ids: list[int], category: str, start: date, end: date
) -> int:
    """Income in the same category over the window — treated as refunds that
    offset the category's spend (a refund-matched pair nets out)."""
    if not acct_ids:
        return 0
    total = db.execute(
        select(func.coalesce(func.sum(IncomeORM.amount), 0)).where(
            IncomeORM.account_id.in_(acct_ids),
            IncomeORM.category == category,
            IncomeORM.date >= start.isoformat(),
            IncomeORM.date < end.isoformat(),
        )
    ).scalar_one()
    return int(total or 0)


# Categories that are internal transfers between the user's own accounts — never
# counted as spend. The canonical category for these in this app is "Transfer".
_TRANSFER_CATEGORIES = {"Transfer", "Transfers"}


def category_baseline(
    db: Session, user_id: int, category: str, as_of: Optional[date] = None
) -> Baseline:
    """Trailing-3-calendar-month average monthly spend for *category* (cents).

    Calendar months, not 90 days. Excludes own-account transfers; nets out
    refund pairs (same-category income). Low-confidence when <6 weeks of data.
    """
    as_of = as_of or date.today()
    acct_ids = _account_ids(db, user_id)
    if not acct_ids:
        return Baseline(0, True)

    window_start = _months_back_start(as_of, BASELINE_MONTHS)
    window_end = _start_of_month(as_of)  # exclude the current partial month

    if category in _TRANSFER_CATEGORIES:
        return Baseline(0, _is_low_confidence(db, user_id, as_of))

    spend = db.execute(
        select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(
            ExpenseORM.account_id.in_(acct_ids),
            ExpenseORM.category == category,
            ExpenseORM.date >= window_start.isoformat(),
            ExpenseORM.date < window_end.isoformat(),
        )
    ).scalar_one()
    refunds = _refund_offset_cents(
        db, acct_ids, category, window_start, window_end
    )
    net = max(int(spend or 0) - refunds, 0)
    monthly = net // BASELINE_MONTHS
    return Baseline(monthly, _is_low_confidence(db, user_id, as_of))


def income_baseline(
    db: Session, user_id: int, as_of: Optional[date] = None
) -> Baseline:
    """Trailing-3-calendar-month average monthly income (cents), excluding
    internal transfers."""
    as_of = as_of or date.today()
    acct_ids = _account_ids(db, user_id)
    if not acct_ids:
        return Baseline(0, True)
    window_start = _months_back_start(as_of, BASELINE_MONTHS)
    window_end = _start_of_month(as_of)
    total = db.execute(
        select(func.coalesce(func.sum(IncomeORM.amount), 0)).where(
            IncomeORM.account_id.in_(acct_ids),
            IncomeORM.category.notin_(_TRANSFER_CATEGORIES),
            IncomeORM.date >= window_start.isoformat(),
            IncomeORM.date < window_end.isoformat(),
        )
    ).scalar_one()
    monthly = int(total or 0) // BASELINE_MONTHS
    return Baseline(monthly, _is_low_confidence(db, user_id, as_of))


def total_spend_baseline(
    db: Session, user_id: int, as_of: Optional[date] = None
) -> Baseline:
    """Trailing-3-month average monthly total spend (cents), all non-transfer
    categories netted of refunds."""
    as_of = as_of or date.today()
    acct_ids = _account_ids(db, user_id)
    if not acct_ids:
        return Baseline(0, True)
    window_start = _months_back_start(as_of, BASELINE_MONTHS)
    window_end = _start_of_month(as_of)
    spend = db.execute(
        select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(
            ExpenseORM.account_id.in_(acct_ids),
            ExpenseORM.category.notin_(_TRANSFER_CATEGORIES),
            ExpenseORM.date >= window_start.isoformat(),
            ExpenseORM.date < window_end.isoformat(),
        )
    ).scalar_one()
    refunds = db.execute(
        select(func.coalesce(func.sum(IncomeORM.amount), 0)).where(
            IncomeORM.account_id.in_(acct_ids),
            IncomeORM.category.notin_(_TRANSFER_CATEGORIES),
            # Only income that looks like a refund (has a spend category twin);
            # for the baseline we conservatively offset using non-Work income.
            IncomeORM.category != "Work",
            IncomeORM.date >= window_start.isoformat(),
            IncomeORM.date < window_end.isoformat(),
        )
    ).scalar_one()
    net = max(int(spend or 0) - int(refunds or 0), 0)
    return Baseline(net // BASELINE_MONTHS, _is_low_confidence(db, user_id, as_of))


def savings_rate_baseline(
    db: Session, user_id: int, as_of: Optional[date] = None
) -> float:
    """Baseline savings rate = (income − spend) / income over the window.

    A ratio in [0, 1]; 0 when income is zero. This is the anchor Mana scores
    against (improvement scores, not absolute wealth).
    """
    inc = income_baseline(db, user_id, as_of).monthly_cents
    spend = total_spend_baseline(db, user_id, as_of).monthly_cents
    if inc <= 0:
        return 0.0
    return max(0.0, (inc - spend) / inc)
