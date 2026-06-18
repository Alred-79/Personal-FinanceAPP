# Overdraft forecast — IID vs block-bootstrap coverage backtest

**Date:** 2026-06-14
**Harness:** `server/scripts/forecast_backtest.py` (offline, stdlib-only, deterministic by seed)
**Change under test:** the overdraft simulator (`server/src/services/forecast_sim.py`) now resamples residuals in contiguous **moving blocks** (`block_days`, default 7) instead of one-per-day IID.

## Why this change

Spending is autocorrelated — spendy and quiet stretches cluster. Drawing one residual per day independently (IID) cancels highs and lows too fast, so the uncertainty band comes out **too narrow** and the overdraft probability reads **overconfident**. For a *safety* number, understating tail risk is the worst error direction. A moving-block bootstrap preserves short-range dependence, so the band reflects realistic streaks.

## Method

Rolling-origin backtest on a synthetic **AR(1)** daily-spend series (φ = 0.6 — positive autocorrelation), so it needs no real user data and is fully reproducible:

- 30-day trailing window → residual pool; 28-day forecast horizon; 400 rolling origins.
- For each origin, forecast the trough band with `block_days=1` (legacy IID) and `block_days=7` (block), then check whether the **5th–95th band covered the realized trough** of the actual next-28-day path.
- Nominal coverage target: **90%**.

Run it yourself: `./.venv/bin/python -m server.scripts.forecast_backtest <seed>`

## Results (seeds 0–2)

| Config | seed 0 | seed 1 | seed 2 | mean band width |
|---|---|---|---|---|
| **IID** (block_days=1) | 0.477 | 0.357 | 0.412 | ~$288 |
| **BLOCK** (block_days=7) | **0.660** | **0.470** | **0.552** | ~$395 |

Empirical overdraft rate was ~0 in all runs (realistic starting balance), so the comparison is purely about band coverage/width.

## Conclusion

- **The change moves coverage in the right direction, every seed.** Block coverage is consistently **higher** than IID (e.g. 0.66 vs 0.48), and the block band is **wider** (~$395 vs ~$288) — exactly the autocorrelation correction intended. The old IID band was measurably overconfident.
- **It does not fully reach 90%, and we are not claiming it does.** Two honest reasons: (1) only ~30 residual days exist, so the pool holds few distinct blocks; (2) the residual model resamples *deviations from a fixed mean burn* and so cannot capture a sustained **level/regime shift** (a month that is structurally pricier than the trailing window). Block bootstrap narrows the gap; it doesn't close it.
- **Net:** ship `block_days=7` as the default — it is strictly more honest than IID at the same cost — but keep the band labeled as an estimate, **not** a guaranteed coverage interval. Reaching nominal coverage would need a level-uncertainty term and/or a time-series conformal wrapper (ACI), which remains future work. `block_days=1` reverts to the legacy behavior if ever needed.

---

# F1 — split-conformal calibration + the change-point router

**Date:** 2026-06-17
**What's new:** the block band above still under-covers (~0.55–0.66 vs 0.90). F1 adds two stdlib moves on top of it — both in the same harness, both no-new-deps.

1. **Split-conformal (CQR) calibration** (`forecast_sim.bootstrap_overdraft(coverage_level=…)`): hold out a tail of the residual pool, fit the predicted 5th–95th interval on the rest, score the held-out (realized-like) troughs by their signed distance *outside* that interval, and widen by the conformal quantile. The reported band is the **union** of the conformal interval with the raw band, so it can only widen — which makes calibrated coverage **≥ the raw baseline by construction**.
2. **Change-point router** (`forecast_changepoint.py`, stdlib CUSUM + permutation test + binary segmentation; wired in `forecast_service._regime_router`): detect a recent spend-level shift and truncate the burn window to the *current regime* before estimating burn + pool, so a level shift isn't averaged away. The detected shift is also surfaced (`forecast.regime_shift`, `ForecastService.detect_spend_regimes`) for the Auditor (F3) and the game's Grace trigger.

## Results — stationary AR(1) (φ=0.6), seeds 0–2

| Config | seed 0 | seed 1 | seed 2 | mean width |
|---|---|---|---|---|
| IID (block_days=1) | 0.480 | 0.360 | 0.417 | ~$288 |
| BLOCK (block_days=7) | 0.642 | 0.470 | 0.550 | ~$394 |
| **BLOCK + CONFORMAL** | **0.828** | **0.665** | **0.705** | ~$703 |

Calibration lifts coverage **toward 0.90 every seed** (e.g. 0.64 → 0.83), and by the only-widen construction it is provably never *below* the block baseline. It is still an **estimate, not a guarantee**: the "calibration observations" are bootstrap resamples, not independent real draws, so the finite-sample guarantee is heuristic at ~30 residual days. Closing the remaining gap is a data-depth problem (CSV/SimpleFIN/PDF backfill), not a method one.

## Results — a recent regime shift (+100% level step, landed 8 days ago)

| Config | coverage (seed 0) | **median-trough error** (seed 0) |
|---|---|---|
| CONFORMAL, no router | 0.260 | **$871** |
| CONFORMAL + router | 0.207 | **$461** |

The router's win is **centering, not interval width**. Under a recent shift, the stale OLD days drag the no-router burn estimate down, so its forecast trough is mis-centered *shallow* — wrong in the exact direction a safety number must not be. The router truncates to the post-shift regime and **roughly halves the median-trough point error** ($871 → $461; same shape across seeds). Coverage *doesn't* reward this — an only-widen conformal mechanically favors the wider *stale* band, and a +100% step is so deep both 90% bands miss it — but the headline number the user reads, and the overdraft-probability direction, are what the router fixes.

## Conclusion (F1)

- Ship calibration on by default (`settings.forecast_coverage_level = 0.90`): strictly ≥ the block baseline, materially closer to nominal, no new deps, determinism preserved (`overdraft_probability` and `trough_median` are computed *before* the calibration draws, so they're byte-identical to the uncalibrated path under a seed).
- Ship the change-point router on by default (`settings.forecast_changepoint_enabled = True`), guarded by a data-density floor so sparse histories are untouched. Judge it by point-centering, not coverage.
- The band stays labeled an **estimate**. Run it yourself: `./.venv/bin/python -m server.scripts.forecast_backtest <seed>`.
