"""Residual **block**-bootstrap overdraft simulation, with split-conformal
calibration of the band.

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

**Calibration (F1).** Even the block band under-covers at this data volume
(docs/FORECAST-BACKTEST.md: ~0.55 against a 0.90 target). When a ``coverage_level``
is supplied, the raw percentile band is wrapped in a **split-conformal (CQR)**
correction: hold out a tail of the residual pool as a calibration set, fit the
predicted interval on the rest, score how far the held-out (realized-like)
troughs fall outside it, and widen by the conformal quantile. The final band is
the **union** of the conformal interval with the raw band, so it can only widen —
which makes calibrated coverage provably ≥ the raw-percentile baseline, the F1
definition of done. It is still an *estimate*, not a guaranteed coverage interval:
the calibration "observations" are bootstrap resamples, not independent real
draws, so the finite-sample guarantee is heuristic at ~30 residual days. The
honest fix for the residual gap is the change-point router (forecast_changepoint)
plus more history (CSV/SimpleFIN backfill).

Caveat (documented, not silent): with only ~30 days of residual history the pool
holds few distinct blocks, so the same stretches repeat across runs — the
correction is real but bounded at this data volume (see docs/FORECAST-BACKTEST.md).

Pure and dependency-free (stdlib ``random``/``statistics``/``math`` only) so it
stays deterministic under an injected ``random.Random`` — no NumPy, no PyMC. All
math is integer cents; callers convert to dollars at their boundary.
"""

from __future__ import annotations

import math
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

# Split-conformal calibration knobs.
# Fraction of the residual pool held out as the calibration set.
_DEFAULT_CALIB_FRACTION = 0.3
# Below this many residual days the pool can't be split into a usable
# train/calibration pair, so calibration is skipped (the band stays the raw
# percentile band, marked ``calibrated: False``).
_MIN_CALIB_POOL = 8
# Each split half must hold at least this many residuals to be meaningful.
_MIN_CALIB_PART = 3


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


def _simulate_troughs(
    starting_cents: int,
    net_by_day_cents: dict[int, int],
    daily_burn_cents: int,
    num_days: int,
    pool: list[int],
    block_days: int,
    rng: random.Random,
    num_sims: int,
) -> tuple[list[int], int]:
    """Run ``num_sims`` forward balance walks over ``pool`` and return the sorted
    per-run troughs plus the count of runs that ever dipped below zero.

    Factored out of :func:`bootstrap_overdraft` so the conformal calibration can
    reuse the exact same path simulation on the train / calibration residual
    splits. Consumes ``rng`` in a fixed order, so seeded callers stay
    deterministic.
    """
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
    return troughs, overdraft_runs


def _conformal_widen(
    starting_cents: int,
    net_by_day_cents: dict[int, int],
    daily_burn_cents: int,
    num_days: int,
    pool: list[int],
    raw_low: int,
    raw_high: int,
    block_days: int,
    rng: random.Random,
    num_sims: int,
    coverage_level: float,
    calib_fraction: float,
) -> tuple[int, int, bool]:
    """Split-conformal (CQR) widening of the raw percentile band.

    Splits ``pool`` (the real residual history, in day order) into a training
    head and a held-out calibration tail. Fits the predicted 5th/95th interval on
    the training residuals, simulates "realized-like" troughs from the calibration
    residuals, scores each by its signed distance OUTSIDE the predicted interval
    (the CQR nonconformity score), and takes the conformal quantile ``q`` at the
    nominal ``coverage_level``. The conformal interval is
    ``[train_low - q, train_high + q]``; the returned band is its **union** with
    the raw full-pool band, so the result can only be wider than raw — which makes
    calibrated coverage ≥ the raw baseline by construction.

    Returns ``(low, high, calibrated)``. ``calibrated`` is ``False`` (band left
    raw) when the pool is too small to split into two usable halves.
    """
    n = len(pool)
    m = round((1.0 - calib_fraction) * n)
    if n < _MIN_CALIB_POOL or m < _MIN_CALIB_PART or (n - m) < _MIN_CALIB_PART:
        return raw_low, raw_high, False

    train = pool[:m]
    calib = pool[m:]

    train_troughs, _ = _simulate_troughs(
        starting_cents, net_by_day_cents, daily_burn_cents, num_days,
        train, block_days, rng, num_sims,
    )
    train_low = _percentile_sorted(train_troughs, 0.05)
    train_high = _percentile_sorted(train_troughs, 0.95)

    calib_troughs, _ = _simulate_troughs(
        starting_cents, net_by_day_cents, daily_burn_cents, num_days,
        calib, block_days, rng, num_sims,
    )
    # CQR nonconformity: how far each calibration trough lands OUTSIDE the
    # predicted interval (negative when comfortably inside).
    scores = sorted(max(train_low - t, t - train_high) for t in calib_troughs)
    k = len(scores)
    # Quantile level over the k conformity scores. NOTE: ``k`` is the number of
    # *calibration simulation* troughs (``num_sims`` from the calib split), not a
    # held-out empirical sample count, so this is the simulated analogue of the
    # split-conformal (k+1)/k inflation — it nudges the level up by one rank to
    # stay conservative on the finite sim set, clamped to 1.0.
    level = min(1.0, math.ceil((k + 1) * coverage_level) / k)
    q = _percentile_sorted(scores, level)

    cal_low = train_low - q
    cal_high = train_high + q
    # Only-widen: union with the raw band guarantees coverage ≥ the raw baseline.
    return min(raw_low, cal_low), max(raw_high, cal_high), True


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
    coverage_level: float | None = None,
    calib_fraction: float = _DEFAULT_CALIB_FRACTION,
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

    When ``coverage_level`` is supplied (e.g. ``0.90``), the band is additionally
    wrapped in a split-conformal (CQR) correction that can only widen it (see
    :func:`_conformal_widen`); the result then also carries ``coverage_level``
    (the nominal target) and ``calibrated`` (whether the conformal step actually
    ran — ``False`` when the pool was too small to split). ``overdraft_probability``
    and ``trough_median`` are computed BEFORE the calibration draws, so they are
    byte-identical to the uncalibrated path under the same seed.
    """
    if num_days <= 0 or num_sims <= 0:
        return {
            "overdraft_probability": 0.0,
            "trough_low": starting_cents,
            "trough_median": starting_cents,
            "trough_high": starting_cents,
        }

    pool = residual_pool_cents or [0]
    troughs, overdraft_runs = _simulate_troughs(
        starting_cents, net_by_day_cents, daily_burn_cents, num_days,
        pool, block_days, rng, num_sims,
    )

    raw_low = _percentile_sorted(troughs, 0.05)
    raw_median = _percentile_sorted(troughs, 0.50)
    raw_high = _percentile_sorted(troughs, 0.95)

    result: dict[str, Any] = {
        "overdraft_probability": round(overdraft_runs / num_sims, 4),
        "trough_low": raw_low,
        "trough_median": raw_median,
        "trough_high": raw_high,
    }

    if coverage_level is not None:
        low, high, calibrated = _conformal_widen(
            starting_cents, net_by_day_cents, daily_burn_cents, num_days,
            # the REAL residual history (not the [0] placeholder) — an empty pool
            # has nothing to calibrate against.
            residual_pool_cents or [],
            raw_low, raw_high, block_days, rng, num_sims,
            coverage_level, calib_fraction,
        )
        result["trough_low"] = low
        result["trough_high"] = high
        result["coverage_level"] = coverage_level
        result["calibrated"] = calibrated

    return result
