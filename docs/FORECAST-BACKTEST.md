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
