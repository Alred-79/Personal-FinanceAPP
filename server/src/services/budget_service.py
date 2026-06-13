"""Envelope budget service.

Works out spent versus limit summaries for budgets, one per category. The money
math stays pure (no DB) in module level helpers so it's easy to unit test:

* ``prorate_limit``: the linear allowance so far this month
* ``apply_rollover``: fold last month's surplus into this month's limit

Every amount here is in integer cents, and the router converts to dollars at the
boundary. "This month" means the calendar month that contains ``today``.
"""

import calendar
from datetime import date
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    Expense as ExpenseORM,
)
from server.src.money import cents_to_dollars


def prorate_limit(monthly_limit_cents: int, days_elapsed: int, days_in_month: int) -> int:
    """Linear allowance so far this month, after *days_elapsed* of *days_in_month*.

    Clamped to ``[0, monthly_limit_cents]``.  Returns integer cents.

    >>> prorate_limit(30000, 15, 30)
    15000
    """
    if days_in_month <= 0 or monthly_limit_cents <= 0:
        return 0
    days_elapsed = max(0, min(days_elapsed, days_in_month))
    return round(monthly_limit_cents * days_elapsed / days_in_month)


def apply_rollover(
    monthly_limit_cents: int, rollover: bool, prior_remaining_cents: int
) -> int:
    """Effective limit is the base plus any surplus carried over.

    Only a positive surplus carries over, and only when *rollover* is enabled
    (an overspend does **not** reduce the next month's limit).

    >>> apply_rollover(20000, True, 5000)
    25000
    >>> apply_rollover(20000, True, -5000)
    20000
    >>> apply_rollover(20000, False, 5000)
    20000
    """
    if rollover and prior_remaining_cents > 0:
        return monthly_limit_cents + prior_remaining_cents
    return monthly_limit_cents


def _month_bounds(today: date) -> tuple[date, date, int, int]:
    """Return (first_day, prev_month_first, days_in_month, days_elapsed)."""
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    first_day = today.replace(day=1)
    if today.month == 1:
        prev_first = date(today.year - 1, 12, 1)
    else:
        prev_first = date(today.year, today.month - 1, 1)
    days_elapsed = today.day
    return first_day, prev_first, days_in_month, days_elapsed


class BudgetService:
    """Budget create, read, update, and delete on the ORM, plus spent versus limit summaries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _user_account_ids(self, user_id: int) -> list[int]:
        return list(
            self.db.execute(
                select(AccountORM.id).where(AccountORM.user_id == user_id)
            )
            .scalars()
            .all()
        )

    def _spent_cents(
        self, account_ids: list[int], category: str, start: date, end: date
    ) -> int:
        """Sum of expense amounts (cents) for *category* in ``[start, end)``."""
        if not account_ids:
            return 0
        total = self.db.execute(
            select(func.sum(ExpenseORM.amount)).where(
                ExpenseORM.account_id.in_(account_ids),
                ExpenseORM.category == category,
                ExpenseORM.date >= start.isoformat(),
                ExpenseORM.date < end.isoformat(),
            )
        ).scalar()
        return int(total or 0)

    def _had_prior_period(
        self, account_ids: list[int], category: str, start: date, end: date
    ) -> bool:
        """Whether the budget could have run in the prior period ``[start, end)``.

        The schema keeps only a single ``monthly_limit`` per (user, category) with
        no created-at, so there is no direct record of "this budget existed last
        month." The available durable signal is whether the category saw any
        expense activity in the prior period: that's the only thing that lets us
        distinguish a brand-new budget (no prior period → no surplus to carry)
        from one that existed and underspent (real surplus to roll over). Without
        this gate, a first-month budget credits a phantom full ``monthly_limit``
        of rollover because ``prior_spent == 0``.
        """
        if not account_ids:
            return False
        hit = self.db.execute(
            select(ExpenseORM.id)
            .where(
                ExpenseORM.account_id.in_(account_ids),
                ExpenseORM.category == category,
                ExpenseORM.date >= start.isoformat(),
                ExpenseORM.date < end.isoformat(),
            )
            .limit(1)
        ).first()
        return hit is not None

    def summarize(
        self, user_id: int, today: date | None = None
    ) -> list[dict[str, Any]]:
        """Return each budget with spent / limit / remaining for this month."""
        today = today or date.today()
        first_day, prev_first, days_in_month, days_elapsed = _month_bounds(today)

        account_ids = self._user_account_ids(user_id)
        budgets = (
            self.db.execute(
                select(BudgetORM).where(BudgetORM.user_id == user_id)
            )
            .scalars()
            .all()
        )

        out: list[dict[str, Any]] = []
        for b in budgets:
            base_limit: int = b.monthly_limit  # type: ignore[assignment]
            rollover = bool(b.rollover)
            category: str = b.category  # type: ignore[assignment]

            # What was spent across the whole current month (first of the month up to the first of the next).
            spent = self._spent_cents(
                account_ids,
                category,
                first_day,
                _add_one_month(first_day),
            )

            # Only carry a surplus when a prior period actually existed. A
            # brand-new budget has no prior period, so prior_spent would be 0 and
            # the old code credited a phantom full ``base_limit`` of rollover. The
            # prior period's limit is this same ``base_limit`` (the schema stores
            # one limit per budget, no historical/per-period limit), so that part
            # was already correct; the missing guard was prior-period existence.
            if rollover and self._had_prior_period(
                account_ids, category, prev_first, first_day
            ):
                prior_spent = self._spent_cents(
                    account_ids, category, prev_first, first_day
                )
                prior_remaining = base_limit - prior_spent
            else:
                prior_remaining = 0
            effective_limit = apply_rollover(base_limit, rollover, prior_remaining)

            prorated = prorate_limit(effective_limit, days_elapsed, days_in_month)

            out.append(
                {
                    "id": b.id,
                    "category": b.category,
                    "monthly_limit": cents_to_dollars(base_limit),
                    "effective_limit": cents_to_dollars(effective_limit),
                    "rollover": rollover,
                    "spent": cents_to_dollars(spent),
                    "remaining": cents_to_dollars(effective_limit - spent),
                    "prorated_target": cents_to_dollars(prorated),
                    "over_budget": spent > effective_limit,
                    "on_pace": spent <= prorated,
                }
            )
        return out


def _add_one_month(first_day: date) -> date:
    """First day of the month after *first_day* (assumes day == 1)."""
    if first_day.month == 12:
        return date(first_day.year + 1, 1, 1)
    return date(first_day.year, first_day.month + 1, 1)
