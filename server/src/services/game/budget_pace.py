"""Discretionary budget-pace check for the green-day verdict (v4 §6.2).

A day is over (MISS-eligible) only when a *discretionary* category is off its
budget pace. Essential categories (rent, groceries, …) can never MISS a day — a
medical bill or a rent payment is not a failure of discipline. This isolates the
"is any non-essential budget off pace today" question so the verdict stays a pure
read of finance truth.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ...models import UserInDB
from server.src.services.budget_service import BudgetService


def discretionary_over_pace(
    db: Session, user: UserInDB, day: date, essentials: set[str]
) -> bool:
    """True if any non-essential budget is off pace as of *day*.

    Uses the prorated ``on_pace`` flag from the budget summary, which compares
    month-to-date spend against the prorated target — the same "budget pace"
    notion the rest of the app uses. Essentials are excluded entirely.
    """
    for summary in BudgetService(db).summarize(user.id, day):
        if summary["category"] in essentials:
            continue
        if not summary["on_pace"]:
            return True
    return False
