"""Residual **block**-bootstrap overdraft simulation.

A point forecast says "your trough is $X". This adds the uncertainty around it:
hold the scheduled flows and the mean daily burn fixed, then resample the user's
own historical daily-spend *variation* (residuals) onto each day across many
forward runs. The spread of per-run troughs is the band; the share of runs that
ever dip below zero is the overdraft probability.

Why blocks, not IID: real spending is autocorrelated — spendy stretches and quiet
stretches cluster (weekends, post-payday runs). Drawing one residual per day
independently (IID) shuffles that structure away, so the highs and lows cancel
too fast and the band comes out **too narrow** — i.e. the overdraft probability
reads *overconfident*, the worst error direction for a safety number. A moving-
block bootstrap instead samples contiguous runs of days, preserving short-range
dependence, so the band reflects realistic streaks. ``block_days=1`` reduces
exactly to the old IID behavior (the back-compat escape hatch).

Caveat (documented, not silent): with only ~30 days of residual history the pool
holds few distinct blocks, so the same stretches repeat across runs — the
correction is real but bounded at this data volume (see docs/FORECAST-BACKTEST.md).

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

# Default moving-block length (days). A weekly block captures the dominant
# day-of-week spending rhythm. Overridable via settings.sim_block_days and the
# function arg; 1 == legacy IID.
DEFAULT_BLOCK_DAYS = 7


def _percentile_sorted(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile of an already-sorted list (q in [0, 1])."""
    if not sorted_vals:
        return 0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = round(q * (len(sorted_vals) - 1))
    return sorted_vals[idx]


def _sample_residual_sequence(
    pool: list[int], num_days: int, block_days: int, rng: random.Random
) -> list[int]:
    """Build a ``num_days``-long residual sequence by moving-block resampling.

    Repeatedly pick a random start in the day-ordered ``pool`` and copy a
    contiguous run of up to ``block_days`` residuals, until ``num_days`` are
    filled. Blocks wrap around the pool end so every start is valid (circular
    block bootstrap), which keeps coverage uniform. ``block_days <= 1`` yields
    the IID draw (one independent pick per day) exactly.
    """
    n = len(pool)
    if block_days <= 1 or n <= 1:
        return [rng.choice(pool) for _ in range(num_days)]
    block = min(block_days, n)
    seq: list[int] = []
    while len(seq) < num_days:
        start = rng.randrange(n)
        for i in range(block):
            seq.append(pool[(start + i) % n])
    return seq[:num_days]


def bootstrap_overdraft(
    starting_cents: int,
    net_by_day_cents: dict[int, int],
    daily_burn_cents: int,
    num_days: int,
    residual_pool_cents: list[int],
    *,
    rng: random.Random,
    num_sims: int = DEFAULT_NUM_SIMS,
    block_days: int = DEFAULT_BLOCK_DAYS,
) -> dict[str, Any]:
    """Simulate ``num_sims`` forward balance walks and summarize the trough.

    ``net_by_day_cents`` maps a 1-based day offset (1..num_days) to that day's
    scheduled net flow (income positive, expense negative). Each simulated day:
    ``balance += net - daily_burn - resampled_residual``. Residuals come from
    ``residual_pool_cents`` (the user's historical daily deviation from mean
    burn), resampled in contiguous ``block_days`` blocks so spending streaks are
    preserved (``block_days=1`` → the legacy IID draw). An empty pool means zero
    variation, so the result collapses to the deterministic walk.

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
        residuals = _sample_residual_sequence(pool, num_days, block_days, rng)
        for offset in range(1, num_days + 1):
            net = net_by_day_cents.get(offset, 0)
            resid = residuals[offset - 1]
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
