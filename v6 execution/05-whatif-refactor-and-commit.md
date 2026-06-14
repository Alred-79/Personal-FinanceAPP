# 05 — Refactor R14 WhatIfService + un-dead the commit

> Sequential execution doc 5 of 8. Requires docs 01-04 green.

## Context
Unify the legacy single-delta What-If onto the new core (without changing its observable behavior),
then make COMMIT real: a `scenario_commit` assistant action creating standing Rules + a PlanOfRecord
+ the `WhatIfCommitted` XP, through the existing propose→confirm flow.

## Tasks (test-first)
1. **Keep `server/src/services/game/whatif.py` tests green** (`test_money_spine.py` pins
   default-delta = 5% floored at $1, unreachable→smallest-achieving, strain_mode→single_action).
   Refactor `simulate` to: keep the R14 policy logic verbatim, then build a single-mutation overlay and
   compute the reach date via the shared goal-math helpers promoted in doc 04. No behavior change; the
   pinned tests stay green unchanged.
   - **Disambiguation:** the helpers to promote are `whatif.py`'s `_months_to_reach` / `_add_months`.
     A *separate* `_add_months` already exists in `recurring_service.py` — do NOT merge them; promote the
     whatif one and leave recurring's untouched (they may differ subtly). The shared module imports the
     whatif copy; recurring keeps its own.
2. **Un-dead `scenario_commit`** in `server/src/services/assistant_service.py`: add it to BOTH
   `SUPPORTED_ACTIONS` (line 496) and `_HANDLED` (line 509) — the pinned
   `_HANDLED == set(SUPPORTED_ACTIONS)` test forces the pair to move together. Keep the legacy
   `whatif_commit` branch intact but out of the allowlist (test_money_spine.py:369 still calls it
   directly).
   - `validate("scenario_commit", {scenario_id, name})` → DB-free normalize + summary string.
   - `execute(...)`, in this order (the order is load-bearing — `plan_id` does not exist until the
     PlanOfRecord is flushed, and the idempotency key references it):
     1. load the scenario overlay;
     2. for each allocation-shaped commitment build a `RuleORM(action_type="allocate",
        target_kind="goal", target_id, conditions=json[{field:"type", op:"eq", value:"income"}],
        action_params=json{...}, enabled=1)`, `db.add` + `db.flush` to get `rule.id`;
     3. insert one `PlanOfRecord` with `rule_ids_json` + `baseline_snapshot_json =
        ScenarioService.evaluate(...)`, then `db.flush` to get `plan_id`;
     4. `record_events([GameEventDraft(stream=f"user:{uid}", type="WhatIfCommitted",
        payload={scenario_id, rule_ids, plan_id}, idempotency_key=f"scenario_commit:{plan_id}")])`.
     - **`action_params` shape:** the rule engine's `_allocation_cents` supports BOTH `{"amount": X}`
       (fixed dollars) and `{"pct": P}` (percent of the triggering income), so either is achievable with
       no engine change. BUT the dead branch at lines 932-942 only ever writes `{"amount": ...}`. Decide
       the overlay→rule mapping explicitly: if a scenario allocation carries a percentage, emit
       `{"pct": P}`; otherwise `{"amount": X}`. If you don't need percentages for v6, scope this to
       `amount`-only and say so — do NOT leave "amount or pct" ambiguous.
     - **`idempotency_key` is NEW:** the dead branch's `record_events` call (lines 945-957) sets NO
       `idempotency_key`. The replay-safety test below depends on adding it — copy-pasting the dead
       branch is not sufficient; the key is what makes the WhatIfCommitted event idempotent.
3. **`server/tests/test_scenario_commit.py`**: propose mints a token; confirm creates the Rule(s) + one
   PlanOfRecord + exactly one WhatIfCommitted (+20 XP); replay the same token → 409, no duplicate
   rule/plan/event; `_HANDLED == set(SUPPORTED_ACTIONS)` still passes.

## Verification checks
- [ ] `./.venv/bin/pytest server/tests/test_money_spine.py server/tests/test_scenario_commit.py server/tests/test_assistant_writes.py -q` → green.
- [ ] `./.venv/bin/pytest server/tests/test_game_stats.py -q` (WhatIfCommitted XP path) → green.

## Risks
- **R3:** move `scenario_commit` into BOTH action sets in one edit (the pinned test is the guard).
- **R4:** replay safety — `reserve_jti` (existing) + the game-event `idempotency_key`.
- **R1:** the WhatIfService refactor must be behavior-preserving (its tests are unchanged).
