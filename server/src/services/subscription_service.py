"""Detects subscriptions and recurring bills.

Finds charges that look like subscriptions: the same merchant coming back on a
regular cadence for about the same amount. The detection heuristic is a pure
function (``detect_subscriptions``) with no DB dependency, tested on its own
apart from the ORM wrapper, as the unit's notes ask.

Stepping through cadences and finding the next charge date reuse the
recurring engine (``recurring_service.next_occurrence``) so the two features
agree on the calendar math.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
)
from server.src.money import cents_to_dollars
from server.src.services.categorization_service import normalize_merchant
from server.src.services.recurring_service import next_occurrence

# Cadence name to its acceptable [min, max] window for the median interval, in days.
_CADENCE_WINDOWS: list[tuple[str, int, int]] = [
    ("weekly", 6, 8),
    ("bi-weekly", 12, 16),
    ("monthly", 27, 33),
    ("quarterly", 85, 95),
    ("annually", 350, 380),
]

# Each charge must be within this fraction of the group's median amount.
_AMOUNT_TOLERANCE = 0.20

# Minimum number of charges before a merchant is considered a subscription.
_MIN_OCCURRENCES = 2


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _classify_cadence(intervals: list[int]) -> Optional[str]:
    """Return a cadence name if the gaps between charges look regular.

    The median gap has to land in a known cadence window, and every single gap
    has to sit close to that median, so a jumpy series like ``[2, 57]``
    (median 29.5) gets rejected instead of being mistaken for "monthly".
    """
    if not intervals:
        return None
    median = statistics.median(intervals)
    cadence = next(
        (name for name, lo, hi in _CADENCE_WINDOWS if lo <= median <= hi), None
    )
    if cadence is None:
        return None
    tolerance = max(4.0, 0.35 * median)
    if any(abs(gap - median) > tolerance for gap in intervals):
        return None
    return cadence


def detect_subscriptions(
    transactions: list[dict[str, Any]],
    as_of: Optional[date] = None,
    lookback_days: int = 180,
) -> list[dict[str, Any]]:
    """Detect subscriptions from a list of expense dicts.

    Each input dict needs ``title`` (str), ``amount`` (positive dollar float)
    and ``date`` (ISO ``YYYY-MM-DD`` str).  Returns a list (sorted by next
    charge date) of:

        {merchant, title, amount, cadence, occurrences, last_date, next_date}
    """
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=lookback_days)

    groups: dict[str, list[tuple[date, float, str]]] = defaultdict(list)
    for tx in transactions:
        merchant = normalize_merchant(tx.get("title", ""))
        if not merchant:
            continue
        d = _parse_date(tx.get("date", ""))
        amount = tx.get("amount")
        if d is None or amount is None or amount <= 0:
            continue
        if d < cutoff:
            continue
        groups[merchant].append((d, float(amount), tx.get("title", "")))

    subscriptions: list[dict[str, Any]] = []
    for merchant, charges in groups.items():
        if len(charges) < _MIN_OCCURRENCES:
            continue
        charges.sort(key=lambda c: c[0])
        dates = [c[0] for c in charges]
        amounts = [c[1] for c in charges]

        median_amount = statistics.median(amounts)
        if median_amount <= 0:
            continue
        # Reject merchants whose charges vary too much to be a fixed bill.
        if any(
            abs(a - median_amount) > _AMOUNT_TOLERANCE * median_amount
            for a in amounts
        ):
            continue

        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        cadence = _classify_cadence(intervals)
        if cadence is None:
            continue

        last_date = dates[-1]
        nxt = next_occurrence(last_date, cadence)
        subscriptions.append(
            {
                "merchant": merchant,
                "title": charges[-1][2],
                "amount": round(median_amount, 2),
                "cadence": cadence,
                "occurrences": len(charges),
                "last_date": last_date.isoformat(),
                "next_date": nxt.isoformat() if nxt else None,
            }
        )

    subscriptions.sort(key=lambda s: s["next_date"] or "")
    return subscriptions


class SubscriptionService:
    """A wrapper over the ORM that finds a user's subscriptions from their expenses."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_subscriptions(
        self, user_id: int, as_of: Optional[date] = None
    ) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(
                select(ExpenseORM)
                .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
                .where(AccountORM.user_id == user_id)
            )
            .scalars()
            .all()
        )
        transactions = [
            {
                "title": r.title,
                "amount": cents_to_dollars(r.amount),  # type: ignore[arg-type]
                "date": r.date,
            }
            for r in rows
        ]
        return detect_subscriptions(transactions, as_of=as_of)
