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

import statistics
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


# Categories that are internal transfers between the user's own accounts — never
# counted as spend. The canonical category for these in this app is "Transfer".
_TRANSFER_CATEGORIES = {"Transfer", "Transfers"}


def _robust_monthly(buckets: list[int]) -> int:
    """Robust per-month estimator across the calendar-month buckets (cents).

    The MEDIAN of the buckets, not the mean. With the usual 3 buckets a
    symmetric trimmed mean (drop min and max) IS the median, and the median
    rejects a single anomalous month — one car-repair splurge or one empty
    month — without a tunable outlier threshold. For an odd count the median is
    one of the input ints, so cents stay exact (no rounding).

    Buckets MUST be the full window (an explicit ``0`` for a month with no
    activity), so partial-history users trend low, exactly as the old
    ``SUM // BASELINE_MONTHS`` did; the ``low_confidence`` flag still guards them.
    """
    if not buckets:
        return 0
    return int(statistics.median(buckets))


def _month_edges(as_of: date, months: int) -> list[tuple[date, date]]:
    """The ``months`` calendar-month [start, end) windows ending just before
    *as_of*'s month, oldest first. e.g. as_of 2026-06-xx, months=3 →
    [(Mar1,Apr1), (Apr1,May1), (May1,Jun1)]."""
    edges: list[tuple[date, date]] = []
    for i in range(months, 0, -1):
        start = _months_back_start(as_of, i)
        end = _months_back_start(as_of, i - 1)
        edges.append((start, end))
    return edges


def _month_buckets(
    db: Session,
    acct_ids: list[int],
    model,
    as_of: date,
    *,
    category: Optional[str] = None,
    exclude_categories: Optional[set[str]] = None,
) -> list[int]:
    """Per-calendar-month summed amounts of *model* over the baseline window —
    one int per month (explicit ``0`` for months with no rows). Length ==
    ``BASELINE_MONTHS``. Optionally filter to a single ``category`` or exclude a
    set of categories (e.g. transfers)."""
    if not acct_ids:
        return [0] * BASELINE_MONTHS
    buckets: list[int] = []
    for start, end in _month_edges(as_of, BASELINE_MONTHS):
        conds = [
            model.account_id.in_(acct_ids),
            model.date >= start.isoformat(),
            model.date < end.isoformat(),
        ]
        if category is not None:
            conds.append(model.category == category)
        if exclude_categories:
            conds.append(model.category.notin_(exclude_categories))
        total = db.execute(
            select(func.coalesce(func.sum(model.amount), 0)).where(*conds)
        ).scalar_one()
        buckets.append(int(total or 0))
    return buckets


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

    if category in _TRANSFER_CATEGORIES:
        return Baseline(0, _is_low_confidence(db, user_id, as_of))

    spend_buckets = _month_buckets(
        db, acct_ids, ExpenseORM, as_of, category=category
    )
    refund_buckets = _month_buckets(
        db, acct_ids, IncomeORM, as_of, category=category
    )
    # Net refunds PER MONTH (clamped at 0 each), so a refund-heavy month can't
    # drag the median negative or bleed into another month's bucket.
    net_buckets = [max(s - r, 0) for s, r in zip(spend_buckets, refund_buckets)]
    monthly = _robust_monthly(net_buckets)
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
    income_buckets = _month_buckets(
        db, acct_ids, IncomeORM, as_of, exclude_categories=_TRANSFER_CATEGORIES
    )
    monthly = _robust_monthly(income_buckets)
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
    spend_buckets = _month_buckets(
        db, acct_ids, ExpenseORM, as_of, exclude_categories=_TRANSFER_CATEGORIES
    )
    # Refund offset = non-transfer, non-Work income (a refund has a spend twin;
    # paychecks are excluded so they don't masquerade as refunds), netted PER
    # MONTH against that month's spend.
    refund_buckets = _month_buckets(
        db, acct_ids, IncomeORM, as_of,
        exclude_categories=_TRANSFER_CATEGORIES | {"Work"},
    )
    net_buckets = [max(s - r, 0) for s, r in zip(spend_buckets, refund_buckets)]
    return Baseline(
        _robust_monthly(net_buckets), _is_low_confidence(db, user_id, as_of)
    )


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
