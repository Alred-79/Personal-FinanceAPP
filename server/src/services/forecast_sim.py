"""Residual-bootstrap overdraft simulation.

A point forecast says "your trough is $X". This adds the uncertainty around it:
hold the scheduled flows and the mean daily burn fixed, then resample the user's
own historical daily-spend *variation* (residuals) onto each day across many
forward runs. The spread of per-run troughs is the band; the share of runs that
ever dip below zero is the overdraft probability.

Pure and dependency-free (stdlib ``random``/``statistics`` only) so it stays
deterministic under an injected ``random.Random`` — no NumPy, no PyMC. All math
is integer cents; callers convert to dollars at their boundary.
"""

from __future__ import annotations

import random
from typing import Any

# Default number of forward simulations. Enough for a stable 5th/95th percentile
# at this horizon length; small enough to be cheap. Module-level so tests can
# shrink it.
DEFAULT_NUM_SIMS = 300


def _percentile_sorted(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile of an already-sorted list (q in [0, 1])."""
    if not sorted_vals:
        return 0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = round(q * (len(sorted_vals) - 1))
    return sorted_vals[idx]


def bootstrap_overdraft(
    starting_cents: int,
    net_by_day_cents: dict[int, int],
    daily_burn_cents: int,
    num_days: int,
    residual_pool_cents: list[int],
    *,
    rng: random.Random,
    num_sims: int = DEFAULT_NUM_SIMS,
) -> dict[str, Any]:
    """Simulate ``num_sims`` forward balance walks and summarize the trough.

    ``net_by_day_cents`` maps a 1-based day offset (1..num_days) to that day's
    scheduled net flow (income positive, expense negative). Each simulated day:
    ``balance += net - daily_burn - resampled_residual``. The residual is drawn
    with replacement from ``residual_pool_cents`` (the user's historical daily
    deviation from mean burn); an empty pool means zero variation, so the result
    collapses to the deterministic walk.

    Returns ``overdraft_probability`` (fraction of runs whose running minimum
    went below zero) and the 5th/50th/95th percentile of the per-run troughs
    (all integer cents).
    """
    if num_days <= 0 or num_sims <= 0:
        return {
            "overdraft_probability": 0.0,
            "trough_low": starting_cents,
            "trough_median": starting_cents,
            "trough_high": starting_cents,
        }

    pool = residual_pool_cents or [0]
    troughs: list[int] = []
    overdraft_runs = 0
    for _ in range(num_sims):
        running = starting_cents
        trough = starting_cents
        for offset in range(1, num_days + 1):
            net = net_by_day_cents.get(offset, 0)
            resid = rng.choice(pool)
            running += net - daily_burn_cents - resid
            if running < trough:
                trough = running
        troughs.append(trough)
        if trough < 0:
            overdraft_runs += 1

    troughs.sort()
    return {
        "overdraft_probability": round(overdraft_runs / num_sims, 4),
        "trough_low": _percentile_sorted(troughs, 0.05),
        "trough_median": _percentile_sorted(troughs, 0.50),
        "trough_high": _percentile_sorted(troughs, 0.95),
    }
