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


def backtest(block_days: int, rng: random.Random) -> dict:
    covered = 0
    widths: list[int] = []
    overdraft_pred: list[float] = []
    overdraft_real = 0
    series = _ar1_series(WINDOW + HORIZON + ORIGINS + 5, rng)
    # Start above the expected horizon spend so paths aren't guaranteed to
    # overdraft (else every trough is negative and coverage is uninformative).
    # ~mean_burn * horizon * 1.6 leaves realistic headroom.
    start_cents = int(MEAN_BURN * HORIZON * 1.6)

    for o in range(ORIGINS):
        window = series[o : o + WINDOW]
        future = series[o + WINDOW : o + WINDOW + HORIZON]
        burn = int(statistics.mean(window))
        pool = [s - burn for s in window]  # daily deviation from mean burn

        sim = bootstrap_overdraft(
            start_cents,
            {},  # no scheduled flows in the synthetic
            burn,
            HORIZON,
            pool,
            rng=rng,
            num_sims=NUM_SIMS,
            block_days=block_days,
        )
        realized = _realized_trough(start_cents, future, burn)
        if sim["trough_low"] <= realized <= sim["trough_high"]:
            covered += 1
        widths.append(sim["trough_high"] - sim["trough_low"])
        overdraft_pred.append(sim["overdraft_probability"])
        if realized < 0:
            overdraft_real += 1

    return {
        "coverage": covered / ORIGINS,
        "mean_width_cents": int(statistics.mean(widths)),
        "mean_pred_overdraft": round(statistics.mean(overdraft_pred), 4),
        "realized_overdraft_rate": round(overdraft_real / ORIGINS, 4),
    }


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print(f"AR(1) phi={PHI}  window={WINDOW}  horizon={HORIZON}  "
          f"origins={ORIGINS}  nominal={NOMINAL:.0%}  seed={seed}\n")
    for label, block in (("IID (block_days=1)", 1), ("BLOCK (block_days=7)", 7)):
        r = backtest(block, random.Random(seed))
        gap = r["coverage"] - NOMINAL
        print(f"{label:>22}: coverage={r['coverage']:.3f} "
              f"(gap {gap:+.3f})  mean_width=${r['mean_width_cents']/100:,.0f}  "
              f"pred_OD={r['mean_pred_overdraft']:.3f} "
              f"real_OD={r['realized_overdraft_rate']:.3f}")
    print("\nExpect IID coverage < BLOCK coverage, with BLOCK nearer the nominal "
          f"{NOMINAL:.0%} — the band IID under-states on autocorrelated spend.")


if __name__ == "__main__":
    main()
