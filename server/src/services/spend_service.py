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
from server.src.money import (
    cents_to_dollars,
    dollars_to_cents,
    round_half_even_cents,
)
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

        paycheck_cents = paycheck_row  # int cents

        # Fixed (recurring) expenses with their recurrence cadence.
        # ``recurrence`` is SELECTed but was previously absent from GROUP BY, so
        # SQLite picked an arbitrary recurrence per group (nondeterministic
        # proration across runs / engines). Every non-aggregated selected column
        # is now in the GROUP BY (incl. ``recurrence``) so the cadence used for
        # proration is the row's real cadence and the result is deterministic.
        fixed_rows = (
            self.db.execute(
                select(ExpenseORM.amount, ExpenseORM.recurrence)
                .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
                .where(
                    ExpenseORM.recurrence.isnot(None),
                    AccountORM.user_id == user.id,
                )
                .group_by(
                    ExpenseORM.title,
                    ExpenseORM.amount,
                    ExpenseORM.category,
                    ExpenseORM.recurrence,
                )
            )
            .all()
        )

        # All math is done in integer cents (matching ``safe_to_spend`` below) so a
        # per-bill + per-goal accumulation can't pick up binary-float drift and the
        # result is exact to the cent. Dollars only re-appear at the return.
        total_fixed_cents = 0
        for amount_cents, recurrence in fixed_rows:
            days = RECURRENCE_TO_DAYS.get(recurrence, 30)
            total_fixed_cents += (amount_cents * 14) // days

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

        total_goal_contributions_cents = 0
        today = datetime.now().date()
        for goal_amount_cents, goal_date_str, goal_progress_cents in goal_rows:
            remaining_cents = goal_amount_cents - (goal_progress_cents or 0)

            if not goal_date_str:
                log.warning(
                    "Goal with amount_cents=%s has no date, skipping it",
                    goal_amount_cents,
                )
                continue
            goal_date = parse_iso_date(goal_date_str)
            if goal_date is None:
                log.warning("Goal has a malformed date %r, skipping it", goal_date_str)
                continue

            days_until_deadline = (goal_date - today).days
            if days_until_deadline > 0:
                total_goal_contributions_cents += (
                    remaining_cents * 14
                ) // days_until_deadline

        savings_pct = float(user.savings_percent or 0)
        savings_cents = round(paycheck_cents * savings_pct / 100)

        remaining_cents = (
            paycheck_cents
            - total_fixed_cents
            - savings_cents
            - max(0, total_goal_contributions_cents)
        )
        return cents_to_dollars(remaining_cents // 2)

    def safe_to_spend(
        self,
        user: UserInDB,
        as_of: Optional[date] = None,
        *,
        include_outlook: bool = True,
        rng=None,
        overlay=None,
    ) -> dict:
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

        An optional ``overlay`` (:class:`ScenarioOverlay`) makes the number
        hypothetical-aware with ZERO change when omitted (R1). It threads through
        every projection (``recurring.*`` and the inner ``forecast``) so
        added/excluded/overridden streams reshape the horizon and bills/income;
        its ``config_overrides`` layer over the user's ``s2s_*`` rules (horizon,
        include_income, include_goals, buffer); its ``balance_override_cents``
        replaces the summed balance; and its ``goal_mutations`` (keyed by
        ``goal_id``) reshape earmarks and contributions in the goals loop.
        """
        as_of = as_of or date.today()

        # Per-user config straight off the ORM row (not threaded through auth).
        # An overlay's ``config_overrides`` layer ON TOP of the stored rules so a
        # hypothetical can flip include_income / buffer / horizon without writing
        # to the DB. Unknown keys are ignored.
        user_row = self.db.execute(
            select(UserORM).where(UserORM.id == user.id)
        ).scalar_one()
        config_overrides: dict = (
            getattr(overlay, "config_overrides", None) or {}
        )

        def _cfg(key: str, default):
            return config_overrides.get(key, default)

        horizon_mode = str(_cfg("s2s_horizon", user_row.s2s_horizon or "paycheck"))
        include_income = bool(_cfg("s2s_include_income", user_row.s2s_include_income))
        include_goals = bool(_cfg("s2s_include_goals", user_row.s2s_include_goals))
        buffer_cents = int(_cfg("s2s_buffer", user_row.s2s_buffer or 0) or 0)

        recurring = RecurringService(self.db)

        # Goal hypotheticals indexed by goal_id (consumed in the goals loop).
        goal_mutations = {
            m.goal_id: m for m in getattr(overlay, "goal_mutations", ()) or ()
        }

        # ── Horizon ───────────────────────────────────────────────────────
        # Default anchor: the next projected paycheck; fall back to
        # end-of-month when there's no recurring income to anchor on.
        horizon_source = horizon_mode
        # True only when the horizon end IS the anchoring paycheck date. In that
        # case the paycheck landing exactly on ``horizon_end`` must NOT count as
        # income for *this* horizon: ``project_cashflows`` uses an inclusive upper
        # bound (``occ <= horizon_end`` in ``project_occurrences``), so without
        # this guard the anchor paycheck inflates spendable by a full pay period.
        anchored_on_paycheck = False
        if horizon_mode == "week":
            horizon_end = as_of + timedelta(days=7)
        elif horizon_mode == "month":
            horizon_end = _end_of_month(as_of)
        else:  # 'paycheck'
            next_pay = recurring.next_paycheck_date(user.id, as_of, overlay=overlay)
            if next_pay is not None:
                horizon_end = next_pay
                anchored_on_paycheck = True
            else:
                horizon_end = _end_of_month(as_of)
                horizon_source = "month_fallback"

        days_remaining = max((horizon_end - as_of).days, 1)

        # ── Current balance ───────────────────────────────────────────────
        # An overlay's ``balance_override_cents`` replaces the summed balance, so
        # a hypothetical can ask "what if I had $X right now?".
        balance_cents = self.db.execute(
            select(func.coalesce(func.sum(AccountORM.balance), 0)).where(
                AccountORM.user_id == user.id
            )
        ).scalar() or 0
        if overlay is not None and overlay.balance_override_cents is not None:
            balance_cents = overlay.balance_override_cents

        # ── Scheduled cashflows to the horizon (Layer A read) ─────────────
        upcoming_bills_cents = 0
        projected_income_cents = 0
        horizon_end_iso = horizon_end.isoformat()
        # When the horizon IS the anchoring paycheck date, exclude exactly ONE
        # income item on that boundary — the single anchoring paycheck — not all
        # income that happens to land that day. project_cashflows is date-sorted,
        # so the first boundary income item is the anchoring paycheck; a second
        # deposit on the same day (e.g. a one-off bonus) still counts.
        anchor_skip_pending = anchored_on_paycheck
        for item in recurring.project_cashflows(
            user.id, as_of, horizon_end, overlay=overlay
        ):
            cents = dollars_to_cents(item["amount"])
            if item["type"] == "expense":
                upcoming_bills_cents += cents
            elif include_income:
                if anchor_skip_pending and item["date"] == horizon_end_iso:
                    anchor_skip_pending = False
                    continue
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
                select(
                    GoalORM.id, GoalORM.amount, GoalORM.date, GoalORM.progress
                ).where(
                    GoalORM.user_id == user.id,
                    GoalORM.completed == 0,
                )
            ).all()
            for goal_id, amount_cents, date_str, progress_cents in goal_rows:
                # A goal_mutation for this goal hypothetically reshapes its
                # amount / target_date / progress before it feeds the math.
                mut = goal_mutations.get(goal_id)
                if mut is not None:
                    if mut.amount_cents is not None:
                        amount_cents = mut.amount_cents
                    if mut.target_date is not None:
                        date_str = mut.target_date
                    if mut.progress_cents is not None:
                        progress_cents = mut.progress_cents
                progress = progress_cents or 0
                goal_earmarks_cents += progress
                goal_date = parse_iso_date(date_str) if date_str else None
                if goal_date is None:
                    continue
                days_to_goal = (goal_date - as_of).days
                if days_to_goal > 0:
                    remaining = max(amount_cents - progress, 0)
                    daily = remaining / days_to_goal
                    # Banker's rounding (not int() truncation) so fractional
                    # cents round the same way as the rest of the money layer.
                    goal_contributions_cents += round_half_even_cents(
                        daily * days_remaining
                    )

        available_cents = (
            balance_cents
            - upcoming_bills_cents
            + projected_income_cents
            - goal_earmarks_cents
            - goal_contributions_cents
            - buffer_cents
        )
        # Floor (not banker's round) on purpose: the daily plan is a spending
        # ceiling, so rounding down keeps the sum of daily plans <= available.
        daily_plan_cents = available_cents // days_remaining

        result: dict = {
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

        if include_outlook:
            # Probabilistic overdraft outlook over the same horizon, delegated to
            # the forecast's burn-aware simulation so both surfaces agree on
            # method. Additive only — the values above are untouched. Game-mode
            # callers pass include_outlook=False to skip the simulation cost,
            # since they read only ``available``/``breakdown``.
            from server.src.services.forecast_service import ForecastService

            fc = ForecastService(self.db).forecast(
                user.id, as_of, horizon_end, include_burn=True, rng=rng,
                overlay=overlay,
            )
            result["overdraft_probability"] = fc["overdraft_probability"]
            result["trough_band"] = fc["trough_band"]
            # F1: the calibrated band's nominal coverage target (e.g. 0.90) and
            # whether calibration actually ran, so the hero surface can say
            # "≈90% chance you stay above $X" instead of hiding the uncertainty.
            result["coverage_level"] = fc.get("coverage_level")
            result["band_calibrated"] = fc.get("band_calibrated", False)

        return result

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
