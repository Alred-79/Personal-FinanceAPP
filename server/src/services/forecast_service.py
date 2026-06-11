"""Cashflow forecasting.

Projects the user's total balance forward over a horizon so they can answer
questions like *"will I make rent on the 1st?"*.

Method
------
Start from the current total balance (sum of all account balances) and walk the
projected **recurring expenses** (from ``RecurringService``) forward
in date order, subtracting each from the running balance. The result is a
running balance timeline plus a summary that calls out the lowest projected
point and whether the balance dips below zero.

Only recurring *expenses* are projected: the schema models recurrence on
expenses, not income, so we deliberately do not invent recurring income.

All math is done in integer **cents**; dollar floats are produced only at the
output boundary.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Account as AccountORM
from ..money import cents_to_dollars, dollars_to_cents
from .recurring_service import RecurringService


class ForecastService:
    """Projects a user's balance over a horizon from recurring expenses."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def current_balance_cents(self, user_id: int) -> int:
        total = self.db.execute(
            select(func.coalesce(func.sum(AccountORM.balance), 0)).where(
                AccountORM.user_id == user_id
            )
        ).scalar()
        return int(total or 0)

    def forecast(
        self,
        user_id: int,
        horizon_start: date,
        horizon_end: date,
    ) -> dict[str, Any]:
        starting_cents = self.current_balance_cents(user_id)

        # Projected recurring expense instances over the horizon (dollar amounts).
        projected = RecurringService(self.db).project_expenses(
            user_id, horizon_start, horizon_end
        )

        # Aggregate expenses by date so the timeline has one point per day with
        # any activity (in chronological order).
        by_date: dict[str, int] = {}
        for item in projected:
            cents = dollars_to_cents(item["amount"])
            by_date[item["date"]] = by_date.get(item["date"], 0) + cents

        running = starting_cents
        lowest = starting_cents
        lowest_date = horizon_start.isoformat()

        timeline: list[dict[str, Any]] = [
            {
                "date": horizon_start.isoformat(),
                "balance": cents_to_dollars(running),
                "change": 0.0,
                "label": "Starting balance",
            }
        ]

        total_expenses_cents = 0
        for day in sorted(by_date):
            change_cents = -by_date[day]  # expenses reduce the balance
            running += change_cents
            total_expenses_cents += by_date[day]
            if running < lowest:
                lowest = running
                lowest_date = day
            timeline.append(
                {
                    "date": day,
                    "balance": cents_to_dollars(running),
                    "change": cents_to_dollars(change_cents),
                    "label": "Projected recurring expenses",
                }
            )

        return {
            "horizon_start": horizon_start.isoformat(),
            "horizon_end": horizon_end.isoformat(),
            "starting_balance": cents_to_dollars(starting_cents),
            "ending_balance": cents_to_dollars(running),
            "lowest_balance": cents_to_dollars(lowest),
            "lowest_date": lowest_date,
            "total_projected_expenses": cents_to_dollars(total_expenses_cents),
            "will_go_negative": lowest < 0,
            "timeline": timeline,
        }
