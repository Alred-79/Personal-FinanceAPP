# Verified Decision Foundations — adversarially revised build plan

**Branch:** `feat/verified-decision-foundations`
**Review status:** revised after critical sub-agent rejection of the initial scope
**Principle:** add reversible identity, non-persistable planning drafts, descriptive forecast evidence, and stronger MCP verification without changing production forecast math or automating money movement.

## 1. Accepted scope

This branch builds five bounded changes, in this order:

1. correct landing forecast claims that imply real-outcome calibration;
2. add bounded MCP lifecycle property tests;
3. add flat, reversible, user-confirmed merchant aliases;
4. add a standalone, non-persistable soft-allocation composer;
5. add a dark forecast evidence pilot only for data that satisfies a strict liquidity/freshness contract.

Explicitly deferred:

- any production forecast, band, probability, burn, or change-point change;
- MAPIE, OR-Tools, RapidFuzz, River, or another new ML/solver dependency;
- a numerical deployment/calibration gate;
- cross-user calibration or pooled analysis;
- automatic merchant merging or transaction rewriting;
- alias effects on lifecycle snapshots, cancellation verification, matching, tax, imports, or other action paths;
- correction-learning categorization (exact per-user correction memory already exists);
- composer saving, builder loading, scenario commit, rules, transfers, debt, or liability planning.

New product behavior ships behind default-off flags. Copy truthfulness and tests are always active.

## 2. Phase 0 — forecast copy truthfulness

The landing browser widget computes per-day simulated percentiles; it does not compare forecasts against subsequently observed outcomes.

Changes:

- replace “measures how often its range contains the real outcome” with language about the spread of simulated paths;
- replace “calibrated ~90%” with “5th–95th simulated range” in rendered copy, comments, and accessible descriptions;
- retain the explanation of weekly-block resampling and regime sensitivity;
- add a focused frontend assertion that prevents real-outcome/calibrated-widget claims from returning.

No visual redesign and no production forecast change.

## 3. Phase 1 — bounded MCP lifecycle properties

Use the existing Hypothesis dev dependency and `RuleBasedStateMachine`. Keep generated sequences service-level and SQLite-backed; keep PostgreSQL/RLS checks deterministic and separate.

Generated lifecycle actions:

- create a key from an allowed scope subset;
- resolve a valid, expired, revoked, unknown, or disabled-owner key;
- revoke a key and attempt a subsequent new resolution;
- issue and verify a scope-bound capability from a resolved principal;
- attempt vault authorization with adequate and inadequate scopes;
- toggle proposal-feature state;
- attempt cross-owner/cross-tenant reads;
- exercise healthy and failed audit-persistence paths.

Invariants:

- issued scopes never exceed the configured allow-list;
- revoked/expired keys cannot begin a new resolved request;
- owner identity and tenant data never cross;
- a capability never widens its principal’s scope set;
- proposal access requires both scope and feature flag;
- structured audit attempts never contain raw financial parameters;
- healthy audit persistence stores only metadata/hashes.

Required semantic boundaries:

- an already-issued capability remains valid until its short TTL expires; revocation blocks new key resolution;
- database audit persistence is best effort and is not a universal read-blocking invariant;
- subset-scoped access is created as a new key, not by mutating/narrowing an existing key;
- mock/inject the clock; never sleep;
- cap generated examples and step count;
- retain minimized failures as fixed regression tests.

Acceptance:

- no scope escalation or cross-tenant read;
- revocation/expiry affects new resolution exactly as documented;
- capability TTL behavior remains unchanged;
- audit failure is observable and non-blocking;
- the normal CI property suite remains bounded and deterministic.

## 4. Phase 2 — flat reversible merchant aliases

### Data contract

Add a tenant-owned `merchant_aliases` sidecar with:

- `user_id`, normalized alias key, normalized canonical key, canonical display label;
- source (`user` only in this branch), created/reverted timestamps, active flag;
- a portable unique constraint that prevents multiple rows for one `(user_id, alias_key)`; re-confirmation reactivates/updates that row transactionally;
- no self-map, no alias-to-alias target, no canonical key that is itself an active alias, and one-hop resolution only.

Do not modify `normalize_merchant()` and do not rewrite transactions.

Every new-table migration must explicitly install its PostgreSQL RLS policy for already-migrated databases and remove that policy before downgrade. Adding the table to `TENANT_TABLES` supplies create-all parity but is not sufficient by itself.

### Service and category conflict rule

Add `MerchantIdentityService`:

- exact normalization;
- one-hop active-alias resolution;
- list distinct, user-owned observed expense descriptors as a capped manual selection corpus;
- create/confirm, list, and revert operations;
- portable transaction-safe duplicate/conflict checks.

Categorization precedence:

1. an exact `source="user"` category mapping for the raw alias key wins;
2. otherwise a confirmed alias may resolve to the canonical merchant mapping;
3. lower-trust exact rule/LLM memory does not override the user-confirmed alias relationship.

Wire aliases only into:

- categorization lookup/learning under the precedence above;
- read-only subscription grouping.

Explicitly do not wire aliases into merchant lifecycle, subscription cancellation/Bridge verification, duplicate/refund matching, tax evidence, or imports in this branch.

### API and UX

Flag: `merchant_aliases_enabled=False`.

Authenticated routes:

- `GET /merchant-aliases/`;
- `GET /merchant-aliases/descriptors/` for capped, user-owned manual choices;
- `POST /merchant-aliases/` with explicit alias/canonical confirmation;
- `DELETE /merchant-aliases/{id}/` as reversible deactivation.

Add a compact manager adjacent to Subscriptions:

- choose two observed descriptors;
- show exactly which descriptor will resolve to which canonical merchant;
- require explicit confirmation;
- list active mappings and undo them;
- label the behavior as grouping, never fraud/identity verification.

Hard fixtures:

- Uber versus Uber Eats;
- Amazon versus Amazon Web Services;
- short/empty/punctuation-only descriptors;
- alias-to-alias and reversed-pair attempts;
- conflicting exact user category memory;
- undo restores exact pre-alias categorization and subscription grouping;
- no lifecycle, tax, matching, import, or assisted-action output changes.

## 5. Phase 3 — standalone soft-allocation composer

### Product contract

The composer answers: “What would the model show if I increased my spending buffer floor and/or soft-earmarked more toward existing goals?”

It does not divide or transfer real money. `s2s_buffer` is presented accurately as a spending floor, not a funded reserve.

Flag: `plan_composer_enabled=False`.

### Deterministic engine

Add a pure, integer-cent `PlanComposerService` that accepts:

- a user-selected maximum soft-allocation amount;
- a desired additional buffer-floor amount;
- selected goal IDs;
- an optional priority (`buffer`, `balanced`, or `deadlines`).

The input amount is capped by the baseline non-negative Safe-to-Spend result. The service must reject foreign, completed, or missing goals.

It deterministically creates and deduplicates a few alternative drafts:

- buffer-floor first;
- balanced;
- deadline-led.

Each draft:

- stores buffer as an absolute proposed value `current_buffer + delta`;
- stores goal progress as absolute proposed values `current_progress + delta`;
- never exceeds the user amount, requested buffer delta, or remaining goal capacity;
- assigns rounding remainder deterministically;
- reports unallocated remainder, assumptions, and model output deltas;
- uses an ephemeral `ScenarioOverlay` internally for `ScenarioService.evaluate()`.

Do not claim Safe-to-Spend falls by exactly the nominal allocation: changing goal progress also changes remaining contribution math. Report the engine’s evaluated output.

### Enforcement and UX

Add a standalone authenticated endpoint (for example `POST /scenarios/compose-preview/`) that returns evaluated cards and allocation breakdowns, but **does not return a persistable overlay**.

The UI is a standalone panel/cards, not part of `ScenarioBuilder`:

- no “Load into builder,” Save, Commit, or Apply control;
- persistent “Soft labels only—nothing moves” disclosure;
- neutral names; never “best,” “optimal,” “recommended,” or “funded”;
- invalid/infeasible input explained without advice language.

Server enforcement, not client copy, guarantees that no generated draft can reach scenario persistence or commit paths.

Acceptance:

- cent-exact deterministic allocation;
- no foreign/completed goals;
- no amount above baseline cap or goal capacity;
- absolute-value overlay math is correct;
- evaluated cards reproduce direct `ScenarioService.evaluate()` results;
- no persistence/commit/action endpoint is reachable from the composer response or UI.

## 6. Phase 4 — forecast evidence pilot

This is descriptive instrumentation, not “real calibration.” It is last because the current forecast sums all account types and Plaid may represent credit debt as a positive balance.

### Eligibility and estimand

An origin is eligible only when all accounts included by the unchanged production forecast are:

- Plaid-linked;
- liquid depository/cash account types with known positive-cash sign semantics;
- fresh at origin and at every subsequent daily observation.

Any credit, loan, investment, unsupported, manual-only, stale, mixed-sign, added, removed, or changed account set invalidates the origin. The pilot never silently filters an unsupported account out of a user-visible all-account forecast.

Operational date is UTC because the app has no per-user timezone contract.

For 7-, 14-, and 30-day horizons, the outcome is the minimum once-daily observed total of the exact same eligible account set from origin through end. This is not an intraday minimum or endpoint balance.

### Storage

Add tenant-owned tables with explicit Alembic-time RLS install/drop:

`forecast_daily_observations`

- immutable first observation per `(user_id, UTC observed_date)`;
- total cents, observed timestamp, account-set hash/count;
- per-source/type counts and freshness metadata;
- eligibility and invalid reason.

`forecast_evidence_origins`

- origin/end dates, horizon, stable model/input/account-set hashes;
- predicted trough low/median/high cents and descriptive overdraft probability;
- nominal configured coverage and whether heuristic widening ran;
- expected/observed days, realized daily trough, status/reason, matured timestamp;
- unique `(user_id, origin_date, horizon_days, model_version)`.

### Capture

Flag: `forecast_evidence_enabled=False`.

- Add one idempotent UTC scheduler job following existing own-session, leader, and RLS rules.
- The job observes current stored balances; it does not trigger or pretend to perform a Plaid refresh.
- Validate account freshness before writing an eligible observation.
- Record the immutable observation before same-day origins.
- Use a stable SHA-256-derived simulation seed.
- Mature only from stored daily observations; never reconstruct an origin with future data.
- Missing/stale days or account-set changes invalidate the origin; never synthesize them.
- Scheduler gaps remain visible as missing evidence.

### Descriptive read surface

Add an authenticated, owner-scoped `/forecast/evidence/` summary, gated by the flag:

- counts and invalid reasons by horizon;
- scheduled capture completeness;
- observed coverage, interval width, and Winkler score for all valid observations;
- a separately predeclared disjoint/non-overlapping origin stream per horizon;
- confidence intervals/effective sample-size caveats;
- event prevalence; no Brier or probability-calibration claim without a separately justified positive-event sample.

No cross-user aggregation and no automatic “sufficient sample” or deployment threshold. A later governance decision is required before pooling users or modifying production bands.

Acceptance:

- unsupported or stale account semantics cannot produce a valid origin;
- every valid outcome uses the same fresh account set on every day;
- production forecast seeded tests remain byte-identical;
- summaries label the evidence descriptive and distinguish overlapping from disjoint origins;
- migration upgrade/downgrade works on SQLite, with explicit PostgreSQL policy SQL and an optional real-Postgres integration run.

## 7. Cross-cutting verification

- New tenant tables: ORM/create-all parity, Alembic upgrade/downgrade, explicit RLS install/drop, ownership/cascade tests.
- New flags: default off, exposed through the existing settings response where needed, and disabled routes return non-disclosing 404s.
- Money: integer cents internally; dollars only at API boundaries.
- Jobs: idempotent, UTC-defined, leader-aware, and safe under missing runs.
- Security: no generated output widens authority or reaches execution.
- Run Ruff, Bandit, dependency audit, backend tests, frontend lint/tests/typecheck, and a local Docker build. Existing branch CI does not provide PostgreSQL or build Docker on pull requests, so those are reported as local/optional verification rather than implied CI coverage.

## 8. Final implementation order

1. copy corrections and regression test;
2. bounded MCP lifecycle state machine;
3. merchant alias schema/migration/service/API, safe consumers, manager, and tests;
4. standalone composer service/preview API/cards and tests;
5. forecast eligibility contract and migrations;
6. evidence capture/maturation/summary and tests;
7. critical review of the implementation, full verification, commit, and push this branch only.
