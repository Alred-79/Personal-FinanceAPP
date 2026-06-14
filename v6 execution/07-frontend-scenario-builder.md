# 07 — Forecast page: full stacked builder + overlay + compare

> Sequential execution doc 7 of 8. Requires docs 01-06 green (the backend contract it consumes).

## Context
Weave the scenario surface into the Forecast page (Engraver's Ledger aesthetic). Full stacked builder,
baseline-vs-scenario chart overlay, saved-scenario picker, compare view, and a real commit affordance
replacing the dead `?commit=N` banner. Conventions: dollar floats on the client; conversion at the API
boundary; Zustand thunks with refetch-after-mutation; AbortController for the live run.

## Tasks (test-first; vitest + jsdom, recharts mocked in client/src/__tests__/setup.ts)
0. **Precondition — shared types/components.** `ForecastPoint` lives in `client/src/store/store.ts`
   (exported there, NOT in `types/index.ts`), and `Figure` is a LOCAL function at the bottom of
   `Forecast.tsx` (not exported). Before the work below:
   - Either import `ForecastPoint` into `types/index.ts` from `@/store/store`, OR move `ForecastPoint`
     to `types/index.ts` and re-export from store (pick one; avoid a store→types→store cycle).
   - Extract `Figure` to a shared `client/src/components/engraving/Figure.tsx` and import it in both
     `Forecast.tsx` and `ScenarioCompare.tsx` (it is NOT reusable across files as-is).
1. **Types** (`client/src/types/index.ts`): `ScenarioMutationKind`, `ScenarioMutation` (discriminated
   union on kind), `ScenarioMutationPayload`, `Scenario`, `ScenarioDiff` (reuse `ForecastPoint` — see
   step 0), `ScenarioResult`.
2. **Store** (`client/src/store/store.ts`): state `scenarios/scenariosLoaded/activeScenarioResult/
   compareResult/committedPlan` — add them to `initialState` so `logout()` resets them (pinned by
   store.test.ts). Thunks: `fetchScenarios/createScenario/updateScenario/deleteScenario` (refetch
   pattern), `runScenario` (AbortController via `inflight.scenarioRun`, like `fetchForecast`),
   `compareScenarios`, `commitScenario` (propose→confirm; on success refetch forecast + goals). Dollar
   floats; `throw` on write failure.
   - Test: `client/src/__tests__/store/scenarios.test.ts` (defaults + logout reset; CRUD; abort/stale
     run; commit refetch).
3. **`client/src/components/custom/ScenarioBuilder/ScenarioBuilder.tsx`** (new): stacked mutation list
   (income / expense / one-off / goal / balance / config), inline editors (Input/Select/Calendar like
   Goals.tsx), name + Save, debounced live `runScenario`. `Stamp` credit/debit per row;
   `Card` + `GuillocheBand` + `SectionRule` framing.
4. **Forecast chart overlay** (`client/src/pages/Forecast/Forecast.tsx`): merge baseline + scenario
   timelines into one dataset; two `Area` series (scenario dashed on `--gold`); `ReferenceArea` for the
   `trough_band` (NOTE: `ReferenceArea` is a NEW recharts import — today only `ReferenceLine`/
   `ReferenceDot` are imported — and `trough_band` is a NEW field the forecast must emit; confirm doc 02's
   forecast output carries `trough_band` before consuming it here, otherwise add it there first);
   overdraft-probability `Stamp`; baseline/what-if `Figure` grid (using the extracted shared `Figure`
   from step 0).
5. **Saved-scenario picker** (`Select`) + **compare mode** (`Tabs`: Projection / What-If / Compare) with
   `client/src/components/custom/ScenarioCompare/ScenarioCompare.tsx` (N+1 series + a comparison
   `ledger-row` table).
6. **Replace the dead banner** (Forecast.tsx:104-132): "Commit this plan" → CommitConfirmDialog wrapping
   the shared `ConfirmCard` (built in doc 08); `?commit=N` / `?goal=` pre-seed the builder.
   - Tests: `client/src/__tests__/components/ScenarioBuilder.test.tsx`,
     `client/src/__tests__/components/ScenarioCompare.test.tsx`,
     `client/src/__tests__/forecast.test.tsx` (banner now has a commit button; overlay renders two
     series).

## Verification checks
- [ ] `npx vitest run client/src/__tests__/store/scenarios.test.ts client/src/__tests__/components/ScenarioBuilder.test.tsx client/src/__tests__/components/ScenarioCompare.test.tsx client/src/__tests__/forecast.test.tsx` → green.
- [ ] Regression: `npx vitest run client/src/__tests__/store/store.test.ts client/src/__tests__/store/fetchers.test.ts` → green (logout reset + abort patterns intact).

## Risks
- `inflight` key collision — use a dedicated `inflight.scenarioRun`.
- `initialState` reset — new keys must be in `initialState` or the logout test fails.
- No nav change here (keeps game-mode snapshots stable).
