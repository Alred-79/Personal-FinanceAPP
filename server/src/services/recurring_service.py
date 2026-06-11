"""Engine that projects recurring transactions.

Takes an expense's ``recurrence`` cadence and expands it into future instances
over a horizon. These projections are worked out on read and never saved as rows.

The math stays pure (no DB access) in the module level functions so it can be
unit tested on its own:

* ``next_occurrence``: one step forward from a date
* ``project_occurrences``: every occurrence strictly after an anchor that falls
  inside a ``[start, end]`` horizon

Calendar cadences (monthly, quarterly, annually) step by whole calendar months
and clamp to the end of the month, so each date lands on the right day instead
of drifting. Fixed cadences (daily, weekly, every two weeks) step by days.

``RECURRENCE_TO_DAYS`` is still the one day count map that ``spend_service``
reuses for its prorated estimate of fixed costs.
"""

import calendar
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
)
from server.src.dates import parse_iso_date
from server.src.money import cents_to_dollars

# The one cadence to day count map (spend_service uses it for proration).
RECURRENCE_TO_DAYS = {
    "daily": 1,
    "weekly": 7,
    "bi-weekly": 14,
    "monthly": 30,
    "quarterly": 91,
    "annually": 365,
}

# Cadence → number of calendar months to advance (None ⇒ use a day delta).
_RECURRENCE_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "annually": 12,
}

# Cadence → number of days to advance.
_RECURRENCE_DAYS = {
    "daily": 1,
    "weekly": 7,
    "bi-weekly": 14,
}

# Guard against runaway loops (say a daily cadence over a horizon spanning years).
_MAX_OCCURRENCES = 5000


def _add_months(d: date, months: int) -> date:
    """Add *months* calendar months to *d*, clamping to the last valid day.

    >>> _add_months(date(2026, 1, 31), 1)
    datetime.date(2026, 2, 28)
    """
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _nth_occurrence(anchor: date, recurrence: str, n: int) -> date | None:
    """The *n*-th occurrence after *anchor* (n >= 1), or None if the cadence is unknown.

    Monthly cadences anchor back to the original day of the month at each step
    instead of drifting off a date that was already clamped, so a series anchored
    on the 31st reads Jan 31, Feb 28, Mar 31, Apr 30, not Feb 28, Mar 28, and so on.
    """
    if recurrence in _RECURRENCE_DAYS:
        return anchor + timedelta(days=_RECURRENCE_DAYS[recurrence] * n)
    if recurrence in _RECURRENCE_MONTHS:
        return _add_months(anchor, _RECURRENCE_MONTHS[recurrence] * n)
    return None


def next_occurrence(d: date, recurrence: str) -> date | None:
    """Return the next occurrence after *d* for *recurrence*, or None if unknown."""
    return _nth_occurrence(d, recurrence, 1)


def project_occurrences(
    anchor: date,
    recurrence: str,
    horizon_start: date,
    horizon_end: date,
) -> list[date]:
    """Project future occurrence dates within ``[horizon_start, horizon_end]``.

    Steps forward from *anchor* (the original transaction date); the anchor
    itself is never included (it's a past/known instance, not a projection).
    Returns dates strictly after *anchor*, ``>= horizon_start`` and
    ``<= horizon_end``, in ascending order.  Unknown cadences yield ``[]``.
    """
    if recurrence not in _RECURRENCE_DAYS and recurrence not in _RECURRENCE_MONTHS:
        return []
    if horizon_end < horizon_start:
        return []

    occurrences: list[date] = []
    for n in range(1, _MAX_OCCURRENCES + 1):
        occ = _nth_occurrence(anchor, recurrence, n)
        if occ is None or occ > horizon_end:
            break
        if occ >= horizon_start:
            occurrences.append(occ)
    return occurrences


class RecurringService:
    """A wrapper over the ORM that projects a user's recurring expenses."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def project_expenses(
        self,
        user_id: int,
        horizon_start: date,
        horizon_end: date,
    ) -> list[dict[str, Any]]:
        """Return projected future expense instances over the horizon.

        Each dict mirrors the transaction shape used elsewhere (dollar amounts),
        plus ``projected: True`` and ``source_id`` (the originating expense row).
        Results are sorted by date ascending.
        """
        rows = (
            self.db.execute(
                select(ExpenseORM)
                .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
                .where(
                    AccountORM.user_id == user_id,
                    ExpenseORM.recurrence.isnot(None),
                )
            )
            .scalars()
            .all()
        )

        projected: list[dict[str, Any]] = []
        for row in rows:
            anchor = parse_iso_date(row.date)  # type: ignore[arg-type]
            if anchor is None:
                continue
            for occ in project_occurrences(
                anchor, row.recurrence, horizon_start, horizon_end  # type: ignore[arg-type]
            ):
                projected.append(
                    {
                        "id": row.id,
                        "source_id": row.id,
                        "title": row.title,
                        "amount": cents_to_dollars(row.amount),  # type: ignore[arg-type]
                        "date": occ.isoformat(),
                        "category": row.category,
                        "recurrence": row.recurrence,
                        "account_id": row.account_id,
                        "type": "expense",
                        "projected": True,
                    }
                )

        projected.sort(key=lambda d: d["date"])
        return projected
