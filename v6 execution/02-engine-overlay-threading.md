# 02 — Thread the overlay through forecast + safe-to-spend

> Sequential execution doc 2 of 8. Requires doc 01 green.

## Context
Make the two probabilistic engines hypothetical-aware by threading the same `overlay` down, plus
balance/config/goal overrides. Reuse the existing burn-aware sim; keep `bootstrap_overdraft` pure.

## Tasks (test-first)
1. **`server/tests/test_forecast.py` / `test_forecast_burn.py` additions**:
   - `forecast(..., overlay=None, rng=random.Random(0))` identical to today (regression pin).
   - `overlay.balance_override_cents` changes `starting_balance`.
   - An added-income overlay raises `lowest_balance` and lowers `overdraft_probability` (seeded rng).
2. **`server/src/services/forecast_service.py`**:
   `forecast(..., *, include_burn=False, rng=None, overlay=None)`; pass `overlay` to
   `project_cashflows`; if `overlay.balance_override_cents is not None` use it instead of
   `current_balance_cents`. Burn + `bootstrap_overdraft` stay pure/unchanged (the overlay only changes
   `starting_cents` and `net_by_offset`).
   - **Output contract:** the forecast result must expose the projected low-point window the frontend
     draws as a `ReferenceArea` (doc 07). If a `trough_band` (or equivalent low-balance window) field is
     not already in the output dict, add it here — it is a NEW field, not assumed to exist. Pin its
     presence/shape with a test assertion in this doc's forecast additions.
3. **`server/tests/test_safe_to_spend.py` additions**: `overlay=None` identical; `config_overrides`
   flip include_income / buffer; `goal_mutations` change earmarks/contributions.
4. **`server/src/services/spend_service.py`**:
   `safe_to_spend(..., *, include_outlook=True, rng=None, overlay=None)`; pass overlay to every
   `recurring.*` call and the inner `forecast`; apply `config_overrides` over the UserORM values; apply
   `balance_override_cents`; apply `goal_mutations` in the goals loop.

## Verification checks
- [ ] `./.venv/bin/pytest server/tests/test_forecast.py server/tests/test_forecast_burn.py server/tests/test_forecast_sim.py server/tests/test_safe_to_spend.py -q` → green.
- [ ] Regression gate: `./.venv/bin/pytest server/tests/test_money_spine.py server/tests/test_homestead.py server/tests/test_game_daily.py -q` → green (game callers pass no overlay).

## Risks
- **R1 (no-op default)** reasserted across both engines.
- **R5 (determinism):** seed the rng in every new probabilistic assertion.
