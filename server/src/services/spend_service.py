"""Spend analytics service, built on the ORM.

Takes a ``Session`` in ``__init__`` (the router hands it in) instead of the old
``BaseDatabridge`` singleton. Money is stored as integer cents, and this service
hands dollar floats back to callers.
"""

import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Optional


def _end_of_month(d: date) -> date:
    """The last day of *d*'s month."""
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])

log = logging.getLogger(__name__)

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.dates import parse_iso_date
from server.src.models import UserInDB
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.services.recurring_service import (
    RECURRENCE_TO_DAYS,
    RecurringService,
)


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

    def safe_to_spend(self, user: UserInDB, as_of: Optional[date] = None) -> dict:
        """The single source of truth for the Safe-to-Spend number (v1 F3).

        Dynamic (recomputed every call) AND anchored (measured to the next
        projected paycheck by default; horizon configurable per user). Each
        component is config-gated by the ``users.s2s_*`` columns, and the
        returned ``breakdown`` lets the UI show *why* the number is what it is.

            available = current_balance
                      − upcoming_bills(to horizon, via project_cashflows)
                      + projected_income(to horizon, if enabled)
                      − goal_earmarks                  # Σ Goal.progress
                      − remaining_goal_contributions
                      − buffer

        All math in integer cents; dollars only at the output boundary.
        """
        as_of = as_of or date.today()

        # Per-user config straight off the ORM row (not threaded through auth).
        user_row = self.db.execute(
            select(UserORM).where(UserORM.id == user.id)
        ).scalar_one()
        horizon_mode: str = user_row.s2s_horizon or "paycheck"
        include_income = bool(user_row.s2s_include_income)
        include_goals = bool(user_row.s2s_include_goals)
        buffer_cents: int = user_row.s2s_buffer or 0

        recurring = RecurringService(self.db)

        # ── Horizon ───────────────────────────────────────────────────────
        # Default anchor: the next projected paycheck; fall back to
        # end-of-month when there's no recurring income to anchor on.
        horizon_source = horizon_mode
        if horizon_mode == "week":
            horizon_end = as_of + timedelta(days=7)
        elif horizon_mode == "month":
            horizon_end = _end_of_month(as_of)
        else:  # 'paycheck'
            next_pay = recurring.next_paycheck_date(user.id, as_of)
            if next_pay is not None:
                horizon_end = next_pay
            else:
                horizon_end = _end_of_month(as_of)
                horizon_source = "month_fallback"

        days_remaining = max((horizon_end - as_of).days, 1)

        # ── Current balance ───────────────────────────────────────────────
        balance_cents = self.db.execute(
            select(func.coalesce(func.sum(AccountORM.balance), 0)).where(
                AccountORM.user_id == user.id
            )
        ).scalar() or 0

        # ── Scheduled cashflows to the horizon (Layer A read) ─────────────
        upcoming_bills_cents = 0
        projected_income_cents = 0
        for item in recurring.project_cashflows(user.id, as_of, horizon_end):
            cents = dollars_to_cents(item["amount"])
            if item["type"] == "expense":
                upcoming_bills_cents += cents
            elif include_income:
                projected_income_cents += cents

        # ── Goals: earmarks + remaining contributions ─────────────────────
        # Earmarks are current Goal.progress — virtual envelopes that make the
        # money "gone" without moving it (so a round-up immediately drops the
        # spendable number). Remaining contributions are the daily pace needed
        # to finish each active goal by its date, over this horizon.
        goal_earmarks_cents = 0
        goal_contributions_cents = 0
        if include_goals:
            goal_rows = self.db.execute(
                select(GoalORM.amount, GoalORM.date, GoalORM.progress).where(
                    GoalORM.user_id == user.id,
                    GoalORM.completed == 0,
                )
            ).all()
            for amount_cents, date_str, progress_cents in goal_rows:
                progress = progress_cents or 0
                goal_earmarks_cents += progress
                goal_date = parse_iso_date(date_str) if date_str else None
                if goal_date is None:
                    continue
                days_to_goal = (goal_date - as_of).days
                if days_to_goal > 0:
                    remaining = max(amount_cents - progress, 0)
                    daily = remaining / days_to_goal
                    goal_contributions_cents += int(daily * days_remaining)

        available_cents = (
            balance_cents
            - upcoming_bills_cents
            + projected_income_cents
            - goal_earmarks_cents
            - goal_contributions_cents
            - buffer_cents
        )
        daily_plan_cents = available_cents // days_remaining

        return {
            "available": cents_to_dollars(available_cents),
            "horizon_end": horizon_end.isoformat(),
            "horizon_source": horizon_source,
            "days_remaining": days_remaining,
            "daily_plan": cents_to_dollars(max(daily_plan_cents, 0)),
            "breakdown": {
                "current_balance": cents_to_dollars(balance_cents),
                "upcoming_bills": cents_to_dollars(upcoming_bills_cents),
                "projected_income": cents_to_dollars(projected_income_cents),
                "goal_earmarks": cents_to_dollars(goal_earmarks_cents),
                "goal_contributions": cents_to_dollars(goal_contributions_cents),
                "buffer": cents_to_dollars(buffer_cents),
            },
            "config": {
                "horizon": horizon_mode,
                "include_income": include_income,
                "include_goals": include_goals,
                "buffer": cents_to_dollars(buffer_cents),
            },
        }

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
