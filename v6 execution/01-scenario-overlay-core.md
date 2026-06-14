# 01 — Scenario Overlay Core (the unifying primitive)

> Sequential execution doc 1 of 8. Do not start doc 02 until this file's
> **Verification checks** block is fully green.

## Context
Introduce `ScenarioOverlay`: a pure, DB-free description of stacked hypotheticals, applied at the
single projection seam so forecast/safe-to-spend/whatif all gain hypotheticals with ZERO behavior
change when no overlay is passed. This is the keystone — everything else builds on it.

The seam: `RecurringService._project_rows` (server/src/services/recurring_service.py:130-181) does one
DB read into `rows`, then a pure expansion loop into `projected[]` (dollar amounts, `source_id`,
`type`, `date`). The overlay applies AFTER the expansion loop ends (~line 178) but BEFORE the existing
`projected.sort(...)` (line 180) — i.e. apply the overlay, then keep the sort so injected/overridden
rows land in date order.

## Tasks (test-first)
1. **Write `server/tests/test_scenario_overlay.py`** (pure, no DB):
   - `ScenarioOverlay.EMPTY` applied to any projected list returns it unchanged (identity).
   - `overlay_from_json(overlay_to_json(x)) == x` round-trip for a fully-populated overlay (the
     cents-discipline guard — proves no float enters storage; all money fields are `*_cents` ints).
   - `apply_to_projected`: excludes by `(kind, source_id)`; overrides an existing row's amount;
     injects an `added_recurring` stream expanded via `project_occurrences`; injects `discrete_flows`
     inside `[horizon_start, horizon_end]` only; re-sorts by date.
   - recurrence-change override == exclude + add (cadence change re-expands correctly).
2. **Implement `server/src/services/scenario_overlay.py`** (no DB, no I/O):
   - Frozen dataclasses:
     - `RecurringAdd(title, amount_cents, recurrence, kind, category="", anchor_date=None)`
     - `RecurringOverride(source_id, kind, amount_cents=None, recurrence=None)`
     - `DiscreteFlow(date, amount_cents, kind, title="", category="")`
     - `GoalMutation(goal_id, amount_cents=None, target_date=None, progress_cents=None, name=None)`
     - `ScenarioOverlay(added_recurring=(), excluded_source_ids=frozenset(), overridden_recurring=(),
       discrete_flows=(), goal_mutations=(), balance_override_cents=None, config_overrides={})`
       + an `EMPTY` module sentinel.
   - `apply_to_projected(projected, horizon_start, horizon_end, *, kind)` — operates on the
     dollar-amount dict shape `_project_rows` builds; **emit `cents_to_dollars(amount_cents)` when
     injecting rows** (R2). Reuse `project_occurrences` from `recurring_service` (do not reimplement
     the date math). Steps: drop excluded `(kind, source_id)`; apply amount overrides; a recurrence
     override = exclude original + add a synthesized stream from the original anchor; append expanded
     `added_recurring`; append in-window `discrete_flows`; re-sort by `date`.
   - `overlay_to_json(overlay)->dict` / `overlay_from_json(d)->ScenarioOverlay` with
     `schema_version: 1`.
3. **Thread `overlay` through `server/src/services/recurring_service.py`**:
   - `_project_rows(..., *, overlay=None)`: after the expansion loop builds `projected` (~line 178) and
     BEFORE the `projected.sort(...)` at line 180, if overlay, call
     `overlay.apply_to_projected(projected, horizon_start, horizon_end, kind=tx_type)`; keep the sort.
   - `project_expenses/project_income/project_cashflows(..., *, overlay=None)` pass-through;
     `project_cashflows` forwards the same overlay to both sub-calls.
   - `next_paycheck_date(..., *, overlay=None)` → forward to `project_income` (income overlays must
     move the anchoring paycheck).
4. **Add `server/tests/test_recurring.py` cases**: `overlay=None` byte-identical to today; an exclude
   overlay drops the source; an add overlay injects expanded occurrences.

## Verification checks
- [ ] `./.venv/bin/pytest server/tests/test_scenario_overlay.py -q` → green.
- [ ] `./.venv/bin/pytest server/tests/test_recurring.py -q` → green (old + new).
- [ ] Regression: `./.venv/bin/pytest server/tests/test_forecast.py server/tests/test_safe_to_spend.py -q`
      → unchanged green (they call `project_cashflows` with no overlay).
- [ ] `grep -n "overlay" server/src/services/recurring_service.py` shows the param defaulted `None`
      on every projection method.

## Risks
- **R1 (no-op default):** `overlay=None`/`EMPTY` must change nothing — pinned by the identity +
  regression tests above.
- **R2 (cents→dollars on injected rows):** `_project_rows` dicts carry dollar amounts; injected rows
  must `cents_to_dollars` — pinned by the inject test.
