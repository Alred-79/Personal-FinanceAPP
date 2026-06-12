"""Cashflow forecasting.

Projects the user's total balance forward over a horizon so they can answer
questions like *"will I make rent on the 1st?"*.

Method
------
Start from the current total balance (sum of all account balances) and walk the
projected **recurring cashflows** — income *and* expenses, from
``RecurringService.project_cashflows`` — forward in date order. Income days add
to the running balance, expense days subtract, and both are netted per date.
The result is a running balance timeline plus a summary that calls out the
lowest projected point and whether the balance dips below zero.

(v1 closed the old schema gap: ``Income.recurrence`` now exists, so the
forecast no longer walks bills down without ever adding the paycheck back —
``will_go_negative`` is no longer falsely pessimistic.)

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
    """Projects a user's balance over a horizon from recurring cashflows."""

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

        # Projected recurring income + expense instances over the horizon
        # (dollar amounts, each tagged ``type``).
        projected = RecurringService(self.db).project_cashflows(
            user_id, horizon_start, horizon_end
        )

        # Net flows per date so the timeline has one point per day with any
        # activity: income positive, expenses negative.
        net_by_date: dict[str, int] = {}
        income_by_date: dict[str, int] = {}
        expense_by_date: dict[str, int] = {}
        for item in projected:
            cents = dollars_to_cents(item["amount"])
            day = item["date"]
            if item["type"] == "income":
                income_by_date[day] = income_by_date.get(day, 0) + cents
                net_by_date[day] = net_by_date.get(day, 0) + cents
            else:
                expense_by_date[day] = expense_by_date.get(day, 0) + cents
                net_by_date[day] = net_by_date.get(day, 0) - cents

        running = starting_cents
        lowest = starting_cents
        lowest_date = horizon_start.isoformat()

        timeline: list[dict[str, Any]] = [
            {
                "date": horizon_start.isoformat(),
                "balance": cents_to_dollars(running),
                "change": 0.0,
                "income": 0.0,
                "expenses": 0.0,
                "label": "Starting balance",
            }
        ]

        total_expenses_cents = 0
        total_income_cents = 0
        for day in sorted(net_by_date):
            change_cents = net_by_date[day]
            running += change_cents
            total_income_cents += income_by_date.get(day, 0)
            total_expenses_cents += expense_by_date.get(day, 0)
            if running < lowest:
                lowest = running
                lowest_date = day
            timeline.append(
                {
                    "date": day,
                    "balance": cents_to_dollars(running),
                    "change": cents_to_dollars(change_cents),
                    "income": cents_to_dollars(income_by_date.get(day, 0)),
                    "expenses": cents_to_dollars(expense_by_date.get(day, 0)),
                    "label": "Projected recurring cashflow",
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
            "total_projected_income": cents_to_dollars(total_income_cents),
            "will_go_negative": lowest < 0,
            "timeline": timeline,
        }
