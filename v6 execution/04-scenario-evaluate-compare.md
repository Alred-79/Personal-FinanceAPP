# 04 — Evaluate + Compare (the diff engine)

> Sequential execution doc 4 of 8. Requires docs 01-03 green.

## Context
Turn a saved overlay into a Baseline-vs-Scenario diff, and an N-way comparison, reusing the
overlay-aware engines from docs 01-02. Diff computed in cents server-side; dollars at the boundary.

## Tasks (test-first)
1. **`server/tests/test_scenario_service.py`**: `evaluate` returns baseline + scenario + per-metric
   delta (overdraft_probability, lowest_balance, ending_balance, safe_to_spend, runway_days, goal_reach
   per goal); baseline uses `ScenarioOverlay.EMPTY` so baseline == live. `compare` for 2 scenarios
   shares ONE seeded `rng` (apples-to-apples). Goal-reach reuses the promoted `_months_to_reach` /
   `_add_months` helpers.
2. **Promote goal-math helpers** out of `server/src/services/game/whatif.py` to a shared module
   (append to `scenario_overlay.py` or a new `goal_math.py`); `whatif.py` imports them (keeps its tests
   green — see doc 05).
3. **`ScenarioService.evaluate(user_id, overlay, *, as_of=None, horizon_days=90, rng=None)`** and
   **`compare(user_id, scenario_ids, *, as_of=None, horizon_days=90, rng=None)`** returning the
   column/delta shape: baseline column + N scenario columns, each `{name, scenario_id?, result, delta}`,
   `delta` = scenario minus baseline in cents (dollars at boundary). `goal_reach` is per-goal
   `{goal_id: {reaches_on, delta_days}}`. Use ONE `random.Random(seed)` across baseline + all columns.
4. **Router**: `POST /scenarios/{id}/evaluate/`, `POST /scenarios/compare/`.
5. **`server/tests/test_scenario_api.py` additions**: evaluate + compare endpoint shapes, auth-gated.

## Verification checks
- [ ] `./.venv/bin/pytest server/tests/test_scenario_service.py server/tests/test_scenario_api.py -q` → green.
- [ ] Determinism: `evaluate` run twice with `rng=random.Random(0)` → identical overdraft_probability.

## Risks
- **R5:** one shared seeded `rng` across baseline + every column (else diffs are noisy).
- **R1:** `EMPTY` baseline must equal live data — asserted.
