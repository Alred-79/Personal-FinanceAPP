"""Coverage backtest: IID vs moving-block residual bootstrap.

OFFLINE harness (not wired into the app) that answers the one question the
block-bootstrap change rests on: *does the new band actually cover the realized
trough at its nominal rate, and does the old IID band under-cover?*

Spending is autocorrelated, so IID resampling produces bands that are too narrow
— they should cover the realized trough less than the nominal 90% (5th–95th) of
the time. The moving-block bootstrap preserves short-range dependence, so its
empirical coverage should sit closer to 90%.

Method (rolling-origin, synthetic so it needs no real user data):
  1. Simulate an AR(1) daily-spend series (positive autocorrelation φ).
  2. For each origin, build the residual pool from the trailing window, forecast
     the next horizon with both block_days=1 (IID) and block_days=7 (block), and
     record whether the band [trough_low, trough_high] covered the REALIZED
     trough of the actual next-horizon path.
  3. Report empirical coverage (target ≈ 0.90) and mean band width for each.

Run:  ./.venv/bin/python -m server.scripts.forecast_backtest
Pure stdlib; deterministic under a fixed seed passed in argv (default 0).
"""

from __future__ import annotations

import random
import statistics
import sys

from server.src.services.forecast_sim import bootstrap_overdraft

WINDOW = 30          # trailing days used to build the residual pool
HORIZON = 28         # days forecast forward
ORIGINS = 400        # rolling origins per configuration
PHI = 0.6            # AR(1) autocorrelation of daily spend (clustering)
MEAN_BURN = 4000     # ~$40/day mean discretionary spend, in cents
NOISE_SD = 1500      # innovation sd, in cents
NUM_SIMS = 300
NOMINAL = 0.90       # 5th–95th band


def _ar1_series(n: int, rng: random.Random) -> list[int]:
    """An AR(1) daily-spend series in cents: x_t = mean + phi*(x_{t-1}-mean)+eps."""
    out: list[int] = []
    prev = MEAN_BURN
    for _ in range(n):
        eps = rng.gauss(0, NOISE_SD)
        val = MEAN_BURN + PHI * (prev - MEAN_BURN) + eps
        val = max(0, val)  # spend can't be negative
        out.append(int(round(val)))
        prev = val
    return out


def _realized_trough(start_cents: int, daily_spend: list[int], burn: int) -> int:
    """Running-minimum balance for an actual spend path (no scheduled flows)."""
    running = start_cents
    trough = start_cents
    for s in daily_spend:
        # balance falls by the day's actual spend; burn is the modeled mean.
        running += -s
        if running < trough:
            trough = running
    return trough


def _ar1_run(n: int, level: int, prev: float, rng: random.Random) -> tuple[list[int], float]:
    """``n`` AR(1) days reverting to ``level`` cents, continuing from ``prev``."""
    out: list[int] = []
    for _ in range(n):
        val = max(0.0, level + PHI * (prev - level) + rng.gauss(0, NOISE_SD))
        out.append(int(round(val)))
        prev = val
    return out, prev


def backtest_recent_shift(
    route: bool,
    seed: int,
    *,
    trials: int = ORIGINS,
    days_since: int = 8,
    shift_delta: int = MEAN_BURN,
) -> dict:
    """Monte-Carlo of a regime shift that JUST happened — the router's home turf.

    Each trial: the trailing window is ``WINDOW − days_since`` days at the OLD
    level followed by ``days_since`` days at the NEW level (a step that landed
    ``days_since`` days ago), and the realized future is HORIZON days at the NEW
    level. ``route`` truncates the window to the detected current regime before
    estimating burn + pool, mirroring the live router.

    Reports coverage AND the median-trough point error: under a recent shift the
    no-router burn is dragged down by the stale OLD days, so its forecast is
    mis-centered (shallow) — the router fixes the *centering*, which coverage (an
    only-widen interval) doesn't reward but the user feels directly."""
    from server.src.services.forecast_changepoint import current_regime_start

    rng = random.Random(seed)
    start_cents = int(MEAN_BURN * HORIZON * 1.6)
    covered = 0
    median_errs: list[int] = []
    for t in range(trials):
        pre, prev = _ar1_run(WINDOW - days_since, MEAN_BURN, MEAN_BURN, rng)
        post, prev = _ar1_run(days_since, MEAN_BURN + shift_delta, prev, rng)
        window = pre + post
        future, _ = _ar1_run(HORIZON, MEAN_BURN + shift_delta, prev, rng)

        w = window
        if route:
            start = current_regime_start(w, rng=random.Random(0))
            if start > 0 and (len(w) - start) >= 7:
                w = w[start:]
        burn = int(statistics.mean(w))
        pool = [s - burn for s in w]
        sim = bootstrap_overdraft(
            start_cents, {}, burn, HORIZON, pool,
            rng=random.Random(seed * 1_000_000 + t),
            num_sims=NUM_SIMS, block_days=7, coverage_level=NOMINAL,
        )
        realized = _realized_trough(start_cents, future, burn)
        if sim["trough_low"] <= realized <= sim["trough_high"]:
            covered += 1
        median_errs.append(abs(sim["trough_median"] - realized))
    return {
        "coverage": covered / trials,
        "median_abs_err_cents": int(statistics.mean(median_errs)),
    }


def backtest(
    block_days: int,
    seed: int,
    *,
    coverage_level: float | None = None,
    route: bool = False,
    series: list[int] | None = None,
) -> dict:
    """Rolling-origin coverage backtest.

    ``coverage_level`` turns on the split-conformal calibration (the calibrated
    band is what coverage is then measured against). ``route`` applies the
    change-point router — truncating each window to its current regime before
    building burn + pool, mirroring ``forecast_service._regime_router``.

    Each origin draws from its OWN ``Random(seed, o)`` — config-independent — so
    that turning routing or calibration on changes the per-origin draw count
    WITHOUT desyncing a shared stream. Without this, two configs would diverge on
    every origin (an artifact), not just where they actually differ.
    """
    from server.src.services.forecast_changepoint import current_regime_start

    covered = 0
    widths: list[int] = []
    overdraft_pred: list[float] = []
    overdraft_real = 0
    median_errs: list[int] = []
    if series is None:
        series = _ar1_series(WINDOW + HORIZON + ORIGINS + 5, random.Random(seed))
    # Start above the expected horizon spend so paths aren't guaranteed to
    # overdraft (else every trough is negative and coverage is uninformative).
    # ~mean_burn * horizon * 1.6 leaves realistic headroom.
    start_cents = int(MEAN_BURN * HORIZON * 1.6)
    origins = min(ORIGINS, len(series) - WINDOW - HORIZON)

    for o in range(origins):
        window = series[o : o + WINDOW]
        future = series[o + WINDOW : o + WINDOW + HORIZON]
        if route:
            # Truncate to the current regime (fixed-seed detection), as the live
            # router does — so a window straddling the shift uses only the new
            # level for its burn + residual pool.
            start = current_regime_start(window, rng=random.Random(0))
            if start > 0 and (WINDOW - start) >= 7:
                window = window[start:]
        burn = int(statistics.mean(window))
        pool = [s - burn for s in window]  # daily deviation from mean burn

        sim = bootstrap_overdraft(
            start_cents,
            {},  # no scheduled flows in the synthetic
            burn,
            HORIZON,
            pool,
            rng=random.Random(seed * 1_000_000 + o),  # per-origin, config-stable
            num_sims=NUM_SIMS,
            block_days=block_days,
            coverage_level=coverage_level,
        )
        realized = _realized_trough(start_cents, future, burn)
        if sim["trough_low"] <= realized <= sim["trough_high"]:
            covered += 1
        widths.append(sim["trough_high"] - sim["trough_low"])
        overdraft_pred.append(sim["overdraft_probability"])
        median_errs.append(abs(sim["trough_median"] - realized))
        if realized < 0:
            overdraft_real += 1

    real_od = overdraft_real / origins
    return {
        "coverage": covered / origins,
        "mean_width_cents": int(statistics.mean(widths)),
        "mean_pred_overdraft": round(statistics.mean(overdraft_pred), 4),
        "realized_overdraft_rate": round(real_od, 4),
        # The router's real wins under a shift: point-centering of the median
        # trough, and overdraft-probability calibration (|pred − realized|).
        "median_abs_err_cents": int(statistics.mean(median_errs)),
        "od_calib_err": round(abs(statistics.mean(overdraft_pred) - real_od), 4),
    }


def _row(label: str, r: dict) -> None:
    gap = r["coverage"] - NOMINAL
    print(f"{label:>26}: coverage={r['coverage']:.3f} "
          f"(gap {gap:+.3f})  mean_width=${r['mean_width_cents']/100:,.0f}  "
          f"med_err=${r['median_abs_err_cents']/100:,.0f}  "
          f"OD_calib_err={r['od_calib_err']:.3f}")


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print(f"AR(1) phi={PHI}  window={WINDOW}  horizon={HORIZON}  "
          f"origins={ORIGINS}  nominal={NOMINAL:.0%}  seed={seed}\n")

    print("── Stationary AR(1): IID vs block vs calibrated ──")
    _row("IID (block_days=1)", backtest(1, seed))
    _row("BLOCK (block_days=7)", backtest(7, seed))
    _row("BLOCK + CONFORMAL", backtest(7, seed, coverage_level=NOMINAL))
    print("\nExpect coverage IID < BLOCK ≤ BLOCK+CONFORMAL — calibration only "
          f"widens, so it can't drop below BLOCK and moves toward {NOMINAL:.0%}.")

    # Recent regime shift (+100% level step that landed 8 days ago): the router's
    # win is CENTERING, not interval width.
    print("\n── Recent regime shift (+100% step, 8 days ago): router vs no-router ──")
    no_router = backtest_recent_shift(False, seed)
    router = backtest_recent_shift(True, seed)
    print(f"      CONFORMAL, no router: coverage={no_router['coverage']:.3f}  "
          f"median_err=${no_router['median_abs_err_cents']/100:,.0f}")
    print(f"        CONFORMAL + router: coverage={router['coverage']:.3f}  "
          f"median_err=${router['median_abs_err_cents']/100:,.0f}")
    print("\nExpect median_err(router) ≪ median_err(no-router): the stale OLD days "
          "drag the no-router burn down, mis-centering the forecast shallow; the "
          "router truncates to the post-shift regime, so the trough lands where "
          "the user actually is. Coverage (an only-widen band) doesn't reward "
          "centering — both miss a +100% step — but the headline number does.")


if __name__ == "__main__":
    main()
