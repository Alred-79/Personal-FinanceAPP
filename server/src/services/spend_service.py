"""Spend analytics service, built on the ORM.

Takes a ``Session`` in ``__init__`` (the router hands it in) instead of the old
``BaseDatabridge`` singleton. Money is stored as integer cents, and this service
hands dollar floats back to callers.
"""

import logging
from datetime import date, datetime
from typing import Optional

log = logging.getLogger(__name__)

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
)
from server.src.dates import parse_iso_date
from server.src.models import UserInDB
from server.src.money import cents_to_dollars
from server.src.services.recurring_service import RECURRENCE_TO_DAYS


class SpendService:
    def __init__(self, db: Session):
        self.db = db

    # ── helpers ───────────────────────────────────────────────────────────

    def _user_account_ids(self, user_id: int):
        """Return all account IDs belonging to *user_id*."""
        return (
            self.db.execute(
                select(AccountORM.id).where(AccountORM.user_id == user_id)
            )
            .scalars()
            .all()
        )

    # ── public API ────────────────────────────────────────────────────────

    def get_budget_allotment(self, user: UserInDB):
        account_ids = self._user_account_ids(user.id)
        if not account_ids:
            return 0

        # Latest "Work" paycheck (most recent by date)
        paycheck_row = self.db.execute(
            select(IncomeORM.amount)
            .join(AccountORM, IncomeORM.account_id == AccountORM.id)
            .where(
                IncomeORM.category == "Work",
                AccountORM.user_id == user.id,
            )
            .order_by(IncomeORM.date.desc())
            .limit(1)
        ).scalar_one_or_none()

        if paycheck_row is None:
            return 0

        paycheck_amount = cents_to_dollars(paycheck_row)

        # Fixed (recurring) expenses with their recurrence cadence
        fixed_rows = (
            self.db.execute(
                select(ExpenseORM.amount, ExpenseORM.recurrence)
                .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
                .where(
                    ExpenseORM.recurrence.isnot(None),
                    AccountORM.user_id == user.id,
                )
                .group_by(ExpenseORM.title, ExpenseORM.amount, ExpenseORM.category)
            )
            .all()
        )

        total_fixed = 0.0
        for amount_cents, recurrence in fixed_rows:
            amount_dollars = cents_to_dollars(amount_cents)
            days = RECURRENCE_TO_DAYS.get(recurrence, 30)
            total_fixed += (amount_dollars * 14) / days

        # Active goals
        goal_rows = (
            self.db.execute(
                select(GoalORM.amount, GoalORM.date, GoalORM.progress).where(
                    GoalORM.user_id == user.id,
                    GoalORM.completed == 0,
                )
            )
            .all()
        )

        total_goal_contributions = 0.0
        today = datetime.now().date()
        for goal_amount_cents, goal_date_str, goal_progress_cents in goal_rows:
            goal_amount = cents_to_dollars(goal_amount_cents)
            goal_progress = cents_to_dollars(goal_progress_cents or 0)
            remaining_amount = goal_amount - goal_progress

            if not goal_date_str:
                log.warning("Goal with amount=%s has no date, skipping it", goal_amount)
                continue
            goal_date = parse_iso_date(goal_date_str)
            if goal_date is None:
                log.warning("Goal has a malformed date %r, skipping it", goal_date_str)
                continue

            days_until_deadline = (goal_date - today).days
            if days_until_deadline > 0:
                daily_contribution = remaining_amount / days_until_deadline
                total_goal_contributions += daily_contribution * 14

        savings_pct = float(user.savings_percent or 0)
        savings_amount = paycheck_amount * (savings_pct / 100)

        remaining_income = (
            paycheck_amount
            - total_fixed
            - savings_amount
            - max(0, total_goal_contributions)
        )
        return remaining_income / 2

    def get_spend_over_time(self, user: UserInDB, start_date: date, end_date: date):
        total = self.db.execute(
            select(func.sum(ExpenseORM.amount))
            .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
            .where(
                ExpenseORM.date.between(str(start_date), str(end_date)),
                ExpenseORM.recurrence.is_(None),
                AccountORM.user_id == user.id,
            )
        ).scalar()

        return cents_to_dollars(total) if total else 0
