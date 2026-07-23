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
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Account as AccountORM, Expense as ExpenseORM
from ..money import cents_to_dollars, dollars_to_cents, round_half_even_cents
from ..settings import settings
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

# --- F1 change-point router knobs ---
# Detection is deterministic under this fixed seed (independent of the forecast's
# own rng, so the bootstrap sim's stream is untouched).
_CHANGEPOINT_SEED = 0
# Need at least this many days with actual spend before trusting regime detection
# — a sparse series has no "level" to shift. (Keeps sparse fixtures untouched.)
_CHANGEPOINT_MIN_NONZERO_DAYS = 10
# Don't truncate the burn window to a regime shorter than this — too little
# post-shift data would wreck the burn estimate and the calibration split.
_CHANGEPOINT_MIN_REGIME_DAYS = 7

# Versioned, privacy-safe seed for consumer forecast/evaluate calls. It is a
# product/model constant rather than a fingerprint of a user's financial data.
_CONSUMER_SIM_SEED_V1 = 20260723


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
        # Activity guard: too few non-recurring transactions ⇒ don't model
        # variation. ``_discretionary_amounts_cents`` is the per-transaction
        # count (the right activity signal); it shares the identical SQL filter
        # with the daily series below, so there's no scope drift.
        amounts = self._discretionary_amounts_cents(user_id, as_of, window_days)
        if len(amounts) < _BURN_MIN_TXNS or window_days <= 0:
            return []
        # Build the pool from the *chronological, day-grouped* daily series — not
        # the unordered amount list — so multiple transactions on one day collapse
        # to a single daily residual and the block bootstrap keeps its day-of-week
        # autocorrelation. The series is already length ``window_days`` (zero-seeded
        # empty days), so an empty day correctly contributes ``-burn``.
        series = self._daily_discretionary_series_cents(user_id, as_of, window_days)
        return [day_total - burn_cents for day_total in series]

    # ── F1: change-point router (the stationarity guard) ───────────────────

    def _daily_discretionary_series_cents(
        self, user_id: int, as_of: date, window_days: int
    ) -> list[int]:
        """Per-day total non-recurring spend (cents) over ``[as_of - window_days,
        as_of)``, in chronological order and length ``window_days`` (empty days
        are 0). This is the *time-ordered* series the change-point detector needs
        — distinct from ``_discretionary_amounts_cents`` (an unordered amount
        list) and from the residual pool (deviations)."""
        if window_days <= 0:
            return []
        window_start = as_of - timedelta(days=window_days)
        rows = self.db.execute(
            select(ExpenseORM.date, ExpenseORM.amount)
            .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
            .where(
                AccountORM.user_id == user_id,
                ExpenseORM.recurrence.is_(None),
                ExpenseORM.date >= window_start.isoformat(),
                ExpenseORM.date < as_of.isoformat(),
            )
        ).all()
        series = [0] * window_days
        for date_str, amount in rows:
            try:
                d = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue
            idx = (d - window_start).days
            if 0 <= idx < window_days:
                series[idx] += int(amount or 0)
        return series

    def detect_spend_regimes(
        self,
        user_id: int,
        as_of: Optional[date] = None,
        window_days: int = _BURN_WINDOW_DAYS,
    ) -> list[dict[str, Any]]:
        """Public regime decomposition of the user's recent daily spend, for F3
        (the Auditor) and the game layer.

        Returns one dict per regime ``{start_date, end_date, days, mean_daily}``
        (dollars), oldest first. Empty when the change-point router is disabled or
        the series is too sparse to trust. Deterministic (fixed-seed detection)."""
        from .forecast_changepoint import segment_regimes

        as_of = as_of or date.today()
        if not settings.forecast_changepoint_enabled or window_days <= 0:
            return []
        series = self._daily_discretionary_series_cents(user_id, as_of, window_days)
        if sum(1 for v in series if v > 0) < _CHANGEPOINT_MIN_NONZERO_DAYS:
            return []
        window_start = as_of - timedelta(days=window_days)
        regimes = segment_regimes(series, rng=random.Random(_CHANGEPOINT_SEED))
        out: list[dict[str, Any]] = []
        for r in regimes:
            out.append(
                {
                    "start_date": (window_start + timedelta(days=r.start)).isoformat(),
                    "end_date": (window_start + timedelta(days=r.end)).isoformat(),
                    "days": r.length,
                    "mean_daily": cents_to_dollars(round(r.mean)),
                }
            )
        return out

    def _regime_router(
        self, user_id: int, as_of: date, window_days: int
    ) -> tuple[int, Optional[dict[str, Any]]]:
        """The router's two outputs: the effective burn window (truncated to the
        current regime when a recent shift is found) and a ``regime_shift``
        summary for narration/F3 (``None`` when stationary).

        Conservative by design: only truncates when the series is dense enough to
        trust AND the current regime is at least ``_CHANGEPOINT_MIN_REGIME_DAYS``
        long, so the calibration split still has support. Pure read; deterministic.
        """
        from .forecast_changepoint import segment_regimes

        if not settings.forecast_changepoint_enabled or window_days <= 0:
            return window_days, None
        series = self._daily_discretionary_series_cents(user_id, as_of, window_days)
        if sum(1 for v in series if v > 0) < _CHANGEPOINT_MIN_NONZERO_DAYS:
            return window_days, None
        regimes = segment_regimes(series, rng=random.Random(_CHANGEPOINT_SEED))
        if len(regimes) < 2:
            return window_days, None  # stationary

        current, prev = regimes[-1], regimes[-2]
        delta_per_day = current.mean - prev.mean
        window_start = as_of - timedelta(days=window_days)
        shift = {
            "date": (window_start + timedelta(days=current.start)).isoformat(),
            "delta_per_day": cents_to_dollars(round(delta_per_day)),
            "delta_per_month": cents_to_dollars(round(delta_per_day * 30)),
            "direction": "up" if delta_per_day > 0 else "down",
        }
        # Truncate the burn window to the current regime only when it has enough
        # support; otherwise keep the full window (the shift is still surfaced).
        effective = (
            current.length
            if current.length >= _CHANGEPOINT_MIN_REGIME_DAYS
            else window_days
        )
        return effective, shift

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
        pass False to keep their existing scheduled-only behavior. ``timeline``
        contains one balance point per calendar day, including both endpoints;
        scheduled cashflow metadata is returned separately in ``events``.

        With ``include_burn`` the result also carries an ``overdraft_probability``
        and a ``trough_band`` (low/median/high dollars) from a residual-bootstrap
        simulation. Pass an ``rng`` (``random.Random(seed)``) to override the
        versioned deterministic consumer seed in tests.

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

        projected = RecurringService(self.db).project_cashflows(
            user_id, horizon_start, horizon_end, overlay=overlay
        )
        net_by_date: dict[str, int] = {}
        income_by_date: dict[str, int] = {}
        expense_by_date: dict[str, int] = {}
        labels_by_date: dict[str, list[str]] = {}
        for item in projected:
            cents = dollars_to_cents(item["amount"])
            iso = item["date"]
            if item["type"] == "income":
                income_by_date[iso] = income_by_date.get(iso, 0) + cents
                net_by_date[iso] = net_by_date.get(iso, 0) + cents
            else:
                expense_by_date[iso] = expense_by_date.get(iso, 0) + cents
                net_by_date[iso] = net_by_date.get(iso, 0) - cents
            title = str(item.get("title") or "Projected recurring cashflow")
            if title not in labels_by_date.setdefault(iso, []):
                labels_by_date[iso].append(title)

        burn_window = _BURN_WINDOW_DAYS
        regime_shift: Optional[dict[str, Any]] = None
        if include_burn:
            burn_window, regime_shift = self._regime_router(
                user_id, horizon_start, _BURN_WINDOW_DAYS
            )
        burn_cents = (
            self._discretionary_burn_cents(
                user_id, horizon_start, window_days=burn_window
            )
            if include_burn
            else 0
        )

        start_iso = horizon_start.isoformat()
        start_net = net_by_date.get(start_iso, 0)
        running = starting_cents + start_net
        lowest = running
        lowest_date = start_iso
        first_negative_date: Optional[str] = start_iso if running < 0 else None
        timeline: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        total_expenses_cents = 0
        total_income_cents = 0
        total_burn_cents = 0

        day = horizon_start
        while day <= horizon_end:
            iso = day.isoformat()
            net_cents = net_by_date.get(iso, 0)
            day_burn = 0 if day == horizon_start else burn_cents
            if day != horizon_start:
                running += net_cents - day_burn
                total_burn_cents += day_burn
            total_income_cents += income_by_date.get(iso, 0)
            total_expenses_cents += expense_by_date.get(iso, 0)
            if running < lowest:
                lowest = running
                lowest_date = iso
            if first_negative_date is None and running < 0:
                first_negative_date = iso
            timeline.append(
                {
                    "date": iso,
                    "balance": cents_to_dollars(running),
                    "change": cents_to_dollars(net_cents - day_burn),
                    "income": cents_to_dollars(income_by_date.get(iso, 0)),
                    "expenses": cents_to_dollars(expense_by_date.get(iso, 0)),
                    "label": "Starting balance" if day == horizon_start else "Central path",
                }
            )
            if iso in net_by_date:
                events.append(
                    {
                        "date": iso,
                        "income": cents_to_dollars(income_by_date.get(iso, 0)),
                        "expenses": cents_to_dollars(expense_by_date.get(iso, 0)),
                        "net": cents_to_dollars(net_cents),
                        "label": ", ".join(labels_by_date.get(iso, [])),
                    }
                )
            day += timedelta(days=1)

        result: dict[str, Any] = {
            "horizon_start": start_iso,
            "horizon_end": horizon_end.isoformat(),
            "starting_balance": cents_to_dollars(starting_cents),
            "ending_balance": cents_to_dollars(running),
            "lowest_balance": cents_to_dollars(lowest),
            "lowest_date": lowest_date,
            "first_negative_date": first_negative_date,
            "total_projected_expenses": cents_to_dollars(total_expenses_cents),
            "total_projected_income": cents_to_dollars(total_income_cents),
            "will_go_negative": lowest < 0,
            "timeline": timeline,
            "events": events,
        }
        if include_burn:
            result["daily_discretionary_burn"] = cents_to_dollars(burn_cents)
            result["total_projected_discretionary"] = cents_to_dollars(
                total_burn_cents
            )
            result["regime_shift"] = regime_shift
            num_days = (horizon_end - horizon_start).days
            net_by_offset: dict[int, int] = {}
            for iso, net_cents in net_by_date.items():
                offset = (date.fromisoformat(iso) - horizon_start).days
                if offset > 0:
                    net_by_offset[offset] = net_cents
            pool = self._burn_residual_pool_cents(
                user_id, horizon_start, burn_cents, window_days=burn_window
            )
            sim = bootstrap_overdraft(
                starting_cents + start_net,
                net_by_offset,
                burn_cents,
                num_days,
                pool,
                rng=rng or random.Random(_CONSUMER_SIM_SEED_V1),
                block_days=settings.sim_block_days,
                coverage_level=settings.forecast_coverage_level or None,
            )
            result["overdraft_probability"] = sim["overdraft_probability"]
            result["paths_below_zero"] = sim["paths_below_zero"]
            result["paths_total"] = sim["paths_total"]
            result["trough_band"] = {
                "low": cents_to_dollars(sim["trough_low"]),
                "median": cents_to_dollars(sim["trough_median"]),
                "high": cents_to_dollars(sim["trough_high"]),
            }
            result["coverage_level"] = sim.get("coverage_level")
            result["band_calibrated"] = sim.get("calibrated", False)
        return result
