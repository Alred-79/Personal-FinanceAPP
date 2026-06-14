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

import random
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Account as AccountORM, Expense as ExpenseORM
from ..money import cents_to_dollars, dollars_to_cents, round_half_even_cents
from .forecast_sim import bootstrap_overdraft
from .recurring_service import RecurringService

# Trailing window (days) over which the discretionary burn rate is estimated.
_BURN_WINDOW_DAYS = 30
# Below this many non-recurring transactions you can't infer a daily spend rate,
# so the burn is treated as zero (and the forecast stays purely scheduled).
_BURN_MIN_TXNS = 3
# Fraction of the largest transactions dropped before averaging — the HistAvg
# trick that keeps a rare big one-off purchase from inflating the daily rate.
_BURN_TOP_FRACTION = 0.10


def hist_avg_daily_burn_cents(
    amounts_cents: list[int],
    window_days: int,
    *,
    top_fraction: float = _BURN_TOP_FRACTION,
    min_txns: int = _BURN_MIN_TXNS,
) -> int:
    """Daily discretionary burn rate (whole cents) from a trailing window.

    The IBM/Cornell "HistAvg" recipe: drop the largest ``floor(N*top_fraction)``
    transactions (rare big one-offs), then divide the sum of what's kept by the
    number of *days* in the window (not by the kept count) — a per-day drain.

    Returns 0 when there's too little to infer a rate (``< min_txns`` or
    ``window_days <= 0``), so a brand-new or quiet account just gets a purely
    scheduled forecast.
    """
    n = len(amounts_cents)
    if window_days <= 0 or n < min_txns:
        return 0
    ordered = sorted(amounts_cents)
    drop = int(n * top_fraction)  # floor
    kept = ordered[: n - drop] if drop else ordered
    return round_half_even_cents(sum(kept) / window_days)


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

    def _discretionary_amounts_cents(
        self, user_id: int, as_of: date, window_days: int
    ) -> list[int]:
        """Individual non-recurring expense amounts (cents) over the trailing
        window ``[as_of - window_days, as_of)``. ``recurrence IS NULL`` is the
        same discretionary filter Safe-to-Spend uses."""
        window_start = as_of - timedelta(days=window_days)
        rows = self.db.execute(
            select(ExpenseORM.amount)
            .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
            .where(
                AccountORM.user_id == user_id,
                ExpenseORM.recurrence.is_(None),
                ExpenseORM.date >= window_start.isoformat(),
                ExpenseORM.date < as_of.isoformat(),
            )
        ).scalars().all()
        return [int(a or 0) for a in rows]

    def _discretionary_burn_cents(
        self, user_id: int, as_of: date, window_days: int = _BURN_WINDOW_DAYS
    ) -> int:
        """Estimate the user's daily discretionary burn (whole cents)."""
        amounts = self._discretionary_amounts_cents(user_id, as_of, window_days)
        return hist_avg_daily_burn_cents(amounts, window_days)

    def _burn_residual_pool_cents(
        self,
        user_id: int,
        as_of: date,
        burn_cents: int,
        window_days: int = _BURN_WINDOW_DAYS,
    ) -> list[int]:
        """Per-day deviation of discretionary spend from the mean daily burn,
        over the trailing window — the bootstrap resample pool. Each window day
        contributes ``(that day's non-recurring spend) - burn``; empty days
        contribute ``-burn`` (a day you spent nothing is below the mean).

        Empty when there's too little history to model variation (so the
        simulation collapses to the deterministic walk)."""
        amounts = self._discretionary_amounts_cents(user_id, as_of, window_days)
        if len(amounts) < _BURN_MIN_TXNS or window_days <= 0:
            return []
        # We don't have per-day grouping here, only the amounts; distribute them
        # across the window's days and pad the rest with zero-spend days. The
        # pool is each day's (spend - burn).
        per_day = amounts + [0] * max(window_days - len(amounts), 0)
        return [a - burn_cents for a in per_day]

    def forecast(
        self,
        user_id: int,
        horizon_start: date,
        horizon_end: date,
        *,
        include_burn: bool = False,
        rng: random.Random | None = None,
        overlay=None,
    ) -> dict[str, Any]:
        """Project the balance forward over [horizon_start, horizon_end].

        When ``include_burn`` is True the projection also drains an estimated
        daily discretionary burn (non-recurring spend) on every day, so the
        trough reflects ordinary day-to-day spending and not just scheduled
        bills — a more honest "will I dip below zero?" answer. Game-mode callers
        pass False to keep their existing scheduled-only behavior. The emitted
        ``timeline`` still carries one point per *activity* day; ``lowest`` and
        ``ending`` are computed over the full daily walk so the burn is felt
        even on days with no scheduled flow.

        With ``include_burn`` the result also carries an ``overdraft_probability``
        and a ``trough_band`` (low/median/high dollars) from a residual-bootstrap
        simulation. Pass an ``rng`` (``random.Random(seed)``) for reproducible
        output in tests; production leaves it None for a fresh, unseeded run.

        An optional ``overlay`` (:class:`ScenarioOverlay`) makes the forecast
        hypothetical-aware: it is threaded down to ``project_cashflows`` (so
        added/excluded/overridden streams reshape ``net_by_offset``), and its
        ``balance_override_cents`` replaces the current total balance as the
        projection's starting point. ``overlay=None`` is a guaranteed no-op — the
        burn estimate and ``bootstrap_overdraft`` stay pure and read the same
        history regardless of the overlay (only ``starting_cents`` and the net
        flows shift).
        """
        starting_cents = self.current_balance_cents(user_id)
        if overlay is not None and overlay.balance_override_cents is not None:
            starting_cents = overlay.balance_override_cents

        # Projected recurring income + expense instances over the horizon
        # (dollar amounts, each tagged ``type``). The overlay reshapes these.
        projected = RecurringService(self.db).project_cashflows(
            user_id, horizon_start, horizon_end, overlay=overlay
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

        burn_cents = (
            self._discretionary_burn_cents(user_id, horizon_start)
            if include_burn
            else 0
        )

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
        total_burn_cents = 0
        # Walk EVERY day so the burn is applied continuously; emit a timeline
        # point only on days with scheduled activity (keeps the payload compact
        # and the existing point-count contract intact).
        day = horizon_start + timedelta(days=1)
        while day <= horizon_end:
            iso = day.isoformat()
            net_cents = net_by_date.get(iso, 0)
            running += net_cents - burn_cents
            total_burn_cents += burn_cents
            total_income_cents += income_by_date.get(iso, 0)
            total_expenses_cents += expense_by_date.get(iso, 0)
            if running < lowest:
                lowest = running
                lowest_date = iso
            if iso in net_by_date:
                timeline.append(
                    {
                        "date": iso,
                        "balance": cents_to_dollars(running),
                        "change": cents_to_dollars(net_cents),
                        "income": cents_to_dollars(income_by_date.get(iso, 0)),
                        "expenses": cents_to_dollars(expense_by_date.get(iso, 0)),
                        "label": "Projected recurring cashflow",
                    }
                )
            day += timedelta(days=1)

        result: dict[str, Any] = {
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
        if include_burn:
            result["daily_discretionary_burn"] = cents_to_dollars(burn_cents)
            result["total_projected_discretionary"] = cents_to_dollars(
                total_burn_cents
            )
            num_days = (horizon_end - horizon_start).days
            # Scheduled net flow keyed by 1-based day offset from horizon_start.
            net_by_offset: dict[int, int] = {}
            for iso, net_cents in net_by_date.items():
                d = date.fromisoformat(iso)
                net_by_offset[(d - horizon_start).days] = net_cents
            pool = self._burn_residual_pool_cents(
                user_id, horizon_start, burn_cents
            )
            sim = bootstrap_overdraft(
                starting_cents,
                net_by_offset,
                burn_cents,
                num_days,
                pool,
                rng=rng or random.Random(),
            )
            result["overdraft_probability"] = sim["overdraft_probability"]
            result["trough_band"] = {
                "low": cents_to_dollars(sim["trough_low"]),
                "median": cents_to_dollars(sim["trough_median"]),
                "high": cents_to_dollars(sim["trough_high"]),
            }
        return result
