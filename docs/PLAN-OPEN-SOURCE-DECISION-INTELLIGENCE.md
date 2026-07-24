# Open-source decision intelligence — implementation plan

**Date:** 2026-07-23

**Implementation status:** this document records the audited pre-implementation baseline and the longer release plan. The `trustworthy-decision-slice` PR implements the immediate account-semantics, signed Safe-to-Spend, capability-gating, first-use, copy-truth, and regression-test subset; later phases remain gated work.

**Decision:** proceed, but do not release or position the current build as a trustworthy prediction product yet.

**Product promise:** **“A private, inspectable money decision tool that shows what is safe to use, what may happen next, and exactly which facts and assumptions produced the answer.”**

This plan supersedes growth-first and feature-first work. Correct financial meaning, reproducibility, and first-use trust are release gates. The existing decision workflow is the product’s strongest asset; the plan preserves it. AI remains optional and is described honestly: deterministic services calculate financial values, the assistant explains or proposes, the user confirms, and verification happens afterward. No copy may imply that an LLM predicts money, that the app has proprietary data, or that its methods are unique.

## 1. Verdict: possible, useful, but not yet proven

### Feasibility

The product is technically feasible as a single-user, local/self-hosted application. The repository already has a typed React client, FastAPI services, integer-cent money, manual and Plaid ingestion, reconciliation review, recurring cash-flow projection, scenario comparison, Safe-to-Spend (S2S), forecast simulation, a dark evidence pilot, a read-only MCP boundary, and propose/confirm/verify assisted actions. Those are substantive assets, not a mockup.

The present blocker is not lack of features. It is that several high-value outputs still start from `SUM(accounts.balance)` even though Plaid’s `current`, `available`, credit, loan, investment, currency, and freshness semantics are not interchangeable. Plaid explicitly defines positive credit and loan balances as amounts owed and distinguishes current from available cash ([Plaid Accounts API](https://plaid.com/docs/api/accounts/)); it also says available balance is normally more useful for near-term funding risk ([Plaid Balance](https://plaid.com/docs/balance/)). Until that distinction is normalized, a polished forecast can be confidently wrong.

### Adoption

There is a credible niche, not evidence of mass-market pull. The strongest initial audience is privacy-conscious people who actively make near-term money decisions and will tolerate self-hosting or manual import. Open source removes subscription and black-box objections, but adds setup, bank-connection, support, and trust burdens. “Free and open source” is distribution, not the value proposition.

The product should earn adoption with one repeated job:

> “Can I do this before my next meaningful cash date, what could make that answer wrong, and what should I review?”

The adoption hypothesis is falsifiable. If first-time users cannot reach and understand one decision answer in five minutes with demo or manual data, or if they do not return to answer another decision within four weeks, stop adding advanced features.

### Truthful market position

Do not claim “better predictions than anyone,” “unique AI,” “proprietary statistics,” or “the only open-source forecast.” Position the app between two established categories:

- Actual Budget and Firefly III demonstrate demand for open-source, user-controlled finance systems. Actual is local-first and keeps data both on device and on the user-selected server ([Actual sync](https://actualbudget.org/docs/getting-started/sync/)); Firefly III is a self-hosted, double-entry personal finance manager with rules, budgets, reports, multi-currency, an API, and Docker distribution ([Firefly III](https://github.com/firefly-iii/firefly-iii)). They set a high bar for ledger correctness, portability, documentation, and community operations.
- Monarch, Copilot, Simplifi, Quicken, PocketSmith, and ProjectionLab demonstrate demand for aggregation, polish, cash-flow projection, and scenarios. The opportunity is not to clone their breadth. It is to make a narrower near-term decision answer inspectable, reconstructable, and locally deployable.

The defensible statement, once this plan ships, is: **“The calculation and its evidence are inspectable, portable, and testable.”** The code and user’s own data are the benefit. The data are not ours and are not proprietary.

## 2. Competitive reality

### Monarch versus Copilot Money

Market facts below are verified **as of 2026-07-23** against the vendors' own public pages. Pricing and beta availability are volatile; re-check them at publication. Ratings, reviews, funding, downloads, and account totals are reach or capital proxies, not evidence of active use, decision completion, or retention.

| Axis | Monarch | Copilot Money | Consequence for this app |
| --- | --- | --- | --- |
| Core job | Broad household money management: aggregation, budgets, goals, reports, collaboration | Automation-first, polished personal aggregation, categorization, spending, budgets, investments, net worth | Do not compete on breadth or visual polish first. Win one decision workflow. |
| Planning | Monarch Forecasting is a Plus feature for long-range net worth, cash flow, and life events; its own documentation calls the results directional, not precise ([Forecasting](https://help.monarch.com/hc/en-us/articles/48344305092244-Forecasting-in-Monarch)) | Core product surfaces cash flow and trends; the new Money Assistant discusses finances but is still beta | Lead with short-horizon, evidence-backed decisions, not retirement planning or generic chat. |
| Scenario timing | Forecasting launched in April 2026. Monarch’s June 16, 2026 release explicitly says users can build and save as many scenarios as they like ([June product update](https://www.monarch.com/blog/june-product-update)). The older May 5 help article still says named scenarios are future work, so it is stale on this point. | No equivalent public claim of generally available saved forecast scenarios was found | Competitor tables must include an “as of” date and never rely on one stale help article. |
| AI / agent status | AI features exist, and Forecasting is generally available in Plus | The Money Assistant and read-only MCP were announced April 16 and May 15, 2026 respectively, but both are beta waitlists, not generally available ([Copilot Dispatch](https://www.copilot.money/dispatch), [waitlist](https://agent.copilot.money/)) | Our working MCP and confirm-before-edit design is meaningful for technical users, but do not claim a durable lead over announced betas. Keep it secondary in onboarding. |
| Pricing | The live official pricing page lists Core at $99.99/year and Plus at **$199.99/year**. The April 20 launch announcement said **$199/year**, so the launch figure is not the current checkout figure ([pricing](https://www.monarch.com/pricing), [Plus launch](https://www.monarch.com/blog/monarch-plus)) | $95/year or $13/month on the official site as of this date ([Copilot pricing](https://www.copilot.money/)) | “Free to self-host” is a real advantage only after setup is zero-external-key, documented, upgrade-safe, and usable without paid aggregation/AI. |
| Adoption evidence | Monarch's own pages publish customer/review marketing, but no comparable current MAU, decision-completion, or retention series | Copilot advertises 4.8/50K ratings on its assistant waitlist, but that is neither assistant adoption nor active use ([assistant waitlist](https://agent.copilot.money/)) | Do not put vendor-reported user totals, ratings, reviews, downloads, or funding into an adoption comparison as if they were retained use. Our adoption case must come from observed activation, repeat decisions, and comprehension. |

### The rest of the field

| Product | What users already get | What to learn; what not to copy |
| --- | --- | --- |
| Actual Budget | Open-source, local-first envelope budgeting, offline operation, user-controlled sync, official Node API ([docs](https://actualbudget.org/docs/api/)) | This is the closest open-source distribution benchmark. An adapter is more useful than rebuilding its ledger. |
| Firefly III | Mature self-hosted ledger, rules, budgets, reports, double-entry, multi-currency, REST API, Docker ([repository](https://github.com/firefly-iii/firefly-iii)) | Treat it as a system of record and pilot a read-only adapter. Do not import by directly querying its database. |
| Quicken Simplifi | Per-account projected cash flow driven by recurring reminders and future-dated transactions ([help](https://support.simplifi.quicken.com/en/articles/3357429-using-projected-cash-flow)) | Users already understand a scheduled-balance chart. Our advantage must be evidence and decision comparison, not merely drawing one. |
| Quicken | Broad desktop depth, projected cash flow, reports, reconciliation, tax-oriented reporting ([plans](https://www.quicken.com/products/pricing-comparison/)) | Breadth is a decades-long moat. It is explicitly a non-goal for v0.1. |
| PocketSmith | Daily forecasts, switchable additive scenarios, calendar planning, multi-currency, and up to 60-year projection by tier ([scenarios](https://learn.pocketsmith.com/article/1248-everything-you-need-to-know-about-scenarios-in-pocketsmith), [pricing](https://my.pocketsmith.com/plans)) | Scenario comparison is established behavior. Use clear on/off assumptions and daily balances; do not claim scenario invention. |
| ProjectionLab | Deep long-term planning, Monte Carlo, historical backtests, what-if compare mode; Premium is $129/year ([pricing](https://projectionlab.com/pricing)) | It owns long-horizon planning. It stopped future self-hosted development and reports 99.4% web usage, implying only about 0.6% self-host usage ([self-host update](https://projectionlab.com/blog/update-on-self-hosting)); this is direct evidence that self-hosting alone does not create adoption. |

## 3. Who uses it, who does not, and where it lives

### Initial user segments

1. **Irregular-income solo worker:** checks before a discretionary purchase, compares a delayed purchase or lower recurring cost, reviews upcoming obligations, and optionally imports statements. Tax is not part of v0.1.
2. **Privacy-first power user:** runs Docker locally or on a home server, imports from an existing ledger, wants an inspectable answer, exports all data, and may connect an external read-only agent.
3. **Financially anxious but engaged user:** needs one calm answer, a visible confidence/data-quality state, and a short list of facts to review—not a dense dashboard or game layer.
4. **Open-source contributor/integrator:** adds an adapter, a baseline, a locale, or a visualization against stable contracts rather than forking product logic.

### Expected use

- First use: demo → “Can I afford a $300 expense before payday?” → inspect answer → change one assumption.
- Weekly: review new transactions and recurring events, resolve data-quality warnings, compare one saved decision.
- Event-driven: income change, major purchase, subscription increase, travel, or a thin-cash period.
- Advanced: self-host, import Actual/Firefly data, or expose explicitly scoped read-only MCP data.

### Expected non-use

- Passive users who only want automatic categorization and a monthly dashboard will prefer Copilot or Monarch.
- Households needing permissions and shared views should use Monarch; this app remains single-user in v0.1.
- Investors, retirees, and advisors needing tax-aware multi-decade planning should use ProjectionLab or professional tools.
- People unwilling to connect, import, or review data will not receive trustworthy personalized output. The app must say so instead of filling screens with fake defaults.
- Users seeking tax filing, investment advice, credit monitoring, money movement, or guaranteed predictions are out of scope.

### Product surface

The app lives first as a responsive local web application distributed through a versioned Docker image and a one-command compose profile. A hosted public demo is a separate, read-only release artifact. A managed cloud service, app-store client, and household hosting are later businesses, not v0.1 requirements. MCP is an optional advanced connection, never the primary first-run path.

## 4. Present value inventory

| User value already present | Current truth | Decision |
| --- | --- | --- |
| Scenario/Decision workflow | Baseline versus scenario timelines, selected horizon, applied/ignored assumptions, modeled trough range, and “X of Y paths below zero” are implemented | Preserve and make this the center of the product. |
| Safe-to-Spend | Signed arithmetic exists, including scheduled bills, optionally included income, goal earmarks/contributions, and buffer | Keep only after the starting-cash and reconstruction contract is corrected. |
| Forecast simulation | Central path plus simulated trough distribution and deterministic evaluation paths exist | Call it modeled, not calibrated or predictive, until forward evidence beats baselines. |
| Evidence pilot | `forecast_daily_observations` and `forecast_evidence_origins` are immutable/scoped; origins use future observations and expose invalid reasons | Correct design, but it is default-off and may be empty. It proves no accuracy today. |
| Hidden data quality | `plaid_balance_refreshed_at`, evidence eligibility, account-set hashes, import discrepancies, and applied/ignored scenario assumptions exist behind the main figures | Surface age, coverage, exclusions, and ignored assumptions beside the decision; hashes stay internal because they do not help a nontechnical user. |
| Import/reconciliation | Imports are staged, user-reviewable, duplicate-aware, and checked via `opening + signed rows = closing`; rows are not written before commit | Valuable. Make reconciliation an analytics authority without allowing unreviewed imports or unsafe balance mutation. |
| Account aggregation | Manual and Plaid accounts work | Current schema collapses balance meanings into one field and loses subtype/currency/available values. P0 blocker. |
| Goals, budgets, subscriptions, rules | Substantive supporting tools | Keep behind a simpler task hierarchy; do not make every feature an onboarding burden. |
| Goal reach | Scenario evaluation derives the contribution pace from the goal deadline and then reports a reach date at that pace | This is circular, not evidence that the user is on track. Use an independently observed or explicitly configured contribution pace; otherwise show `unknown`. The deadline is a comparator, never an input that manufactures its own success. |
| Merchant lifecycle | The backend stores `probability_alive`, expected purchases, cadence, price-change percentage, and a status snapshot | Prefer understandable evidence—last charge, expected window, amount change, and “may be inactive”—over an unexplained probability. Do not expose a raw probability until held-out evaluation and minimum history are documented. |
| Subscription burden | The register totals every detected row, including dormant/low-probability merchants, while cards describe some as possibly inactive | Split **confirmed/likely active recurring burden** from **needs-review possible burden**. Never annualize a dormant row into the headline without labeling the assumption, and never apply the price increase twice. |
| Assistant and MCP | PII scrubbing, read-only scoped MCP, audited reads, and confirm-before-edit paths are meaningful | Message as optional connections. The deterministic engine owns numbers. Core startup must require zero AI/Plaid keys. |
| Landing forecast | A bespoke browser simulation is described as a faithful slice of production, while its hard-coded vignettes are not generated by the server contract | Treat it as an illustrative sandbox or generate it from a checked canonical fixture. The current S2S vignette is arithmetically wrong: its listed components sum to $2,500, not the displayed $850. |
| Demo | Canonical seed, readiness checks, and read-only guards exist | The audited stale/missing demo database is a P0 release-artifact failure. The fail-closed readiness design is correct and must remain. Evidence: `.audit-first-time-user/36-demo-signup-failure.jpg` and `.audit-first-time-user/30-demo-link-bank-disabled.jpg`. |
| Visual/game layer | Distinctive and extensive | Dormant features still create navigation, cognitive, test, bundle, and maintenance cost. Default to a calm decision workspace; load optional game surfaces only after explicit choice. |
| Tax | Rich but feature-flagged | Keep `tax_features_enabled=false`. Landing, seed, and onboarding must not imply availability until the tax contracts are independently repaired and reviewed. |

## 5. Audit findings: confirmed, corrected, and refuted

### Confirmed blockers

- Generic balance semantics corrupt purpose-specific totals: `ForecastService`, `SpendService`, `NetWorthService`, the Accounts page, snapshots, and demo readiness sum the same column.
- Plaid ingestion currently selects `available` else `current` and drops the distinction; it also does not persist subtype or currency on `Account`.
- Forecast evidence correctly refuses unsupported/stale account sets, but production forecast/S2S do not share that eligibility contract.
- A first-time user can encounter demo unavailability, an unknown-route blank surface, confusing signed-out deep-link behavior, missing semantic hierarchy, undersized mobile targets, and visually active controls whose value is unclear. See `.audit-first-time-user/31-unknown-route.jpg`, `35-signed-out-deep-link.jpg`, `38-mobile-navigation.jpg`, and `32-new-user-overview.jpg`.
- Current route and feature breadth exposes empty or disabled surfaces before a user has a useful answer.
- Forecast accuracy has not been demonstrated against future outcomes or a naive baseline.
- Goal reach is tautological where the deadline determines the pace used to “predict” the deadline.
- The Overview clamps negative S2S to zero, combines it with spend from a potentially different period, and renders a reassuring utilization gauge. A negative answer must remain signed; a gauge must use one disclosed horizon and denominator or be removed.
- Initial client state contains `$1` allotment and `$1` spent fallbacks, which can flash as `$1 / $1 · 100%`; empty/loading/failed states must never become financial facts.
- Subscription burden includes dormant or low-probability rows without separating confirmed burden from possible burden.
- Sparse inputs can still render hundreds of identical simulated paths as `0 of 300`; replication is not uncertainty and must collapse to a deterministic insufficient-history state.
- The public landing mixes illustrative client-only math with production claims and contains the $2,500-versus-$850 S2S vignette error.
- Registration can be closed while the login page still offers a complete Sign Up flow, ending only after submission with a recoverable 409.
- A configured Clerk request can end at a generic “try again” response with no retry action or preserved explanation; an unconfigured Clerk should not look available.
- `CardTitle` renders a `div`, so visually prominent card titles do not create document structure; several icon controls and hover-only actions are below the 44px target.
- The audited demo decision subtracts a large purchase from a comfortably positive balance and reports `0 of 300`; it proves arithmetic, not that the tool changes a borderline decision.

### Corrected/refuted claims

- **“The evidence pilot is leakage-prone.”** Refuted for its intended scope: origins are captured before outcomes, daily observations are immutable, account-set changes invalidate, and future data are not reconstructed. The real issue is that it is off/empty and currently describes a narrower eligible population than production calculations.
- **“Reconciliation has no analytical value.”** Refuted: it can establish a higher-authority transaction set and locate a signed discrepancy. It must not, however, let an unreviewed import affect analytics or silently mutate a Plaid balance. A reconciled statement is evidence, not automatic permission.
- **“The demo’s fail-closed check is broken.”** Refuted. Failing closed on an outdated schema/seed is correct. Shipping a demo service whose database was not migrated and reseeded is the P0 release failure.
- **“S2S contradicts the forecast trough.”** Usually a hierarchy/definition failure, not an arithmetic contradiction. S2S is a spend ceiling after obligations, goal pace, and buffer over a chosen horizon; the trough is the lowest modeled account balance along forecast paths. Both can be correct and different. The UI must show their equations and purpose, never place them as unlabeled peer predictions.
- **“Copilot already broadly ships its assistant and MCP.”** Incorrect as of 2026-07-23: both are beta waitlists.
- **“Monarch cannot save scenarios.”** Stale: the feature shipped in the June 16 release even though an older help article still says it is future work.
- **“Open source gives us unique data or unique prediction methods.”** Refuted. Users own their data; methods are inspectable, not exclusive. The advantage is verifiability and extensibility.

## 6. Metric contract — one financial language

Create `server/src/domain/money_metrics.py` as the pure contract module and `server/src/services/account_semantics.py` as the SQLAlchemy adapter. All REST, UI, MCP, evidence, and game readers consume the same versioned contract.

### Account facts

Persist, without lossy conversion:

- `account_type`, `account_subtype`;
- `current_balance_cents`, nullable `available_balance_cents`, nullable `credit_limit_cents`;
- `iso_currency_code` or `unofficial_currency_code`, never an invented silent default;
- `source` (`manual`, `plaid`, `actual`, `firefly`), `source_account_id`, `observed_at`, `freshness_state`;
- `semantic_role` (`liquid_asset`, `nonliquid_asset`, `liability`, `restricted`, `unknown`) and `review_state`.

For a reporting currency of USD in v0.1:

- `asset_total_cents = Σ asset current values`, with asset contributions positive;
- `liability_total_cents = Σ max(amount_owed, 0)`; a Plaid positive credit/loan balance is owed, not cash;
- `net_worth_cents = asset_total_cents - liability_total_cents`;
- `liquid_current_cents = Σ current for eligible liquid assets`;
- `liquid_available_cents = Σ available where present`; missing available values are not zero and are not silently replaced in the field itself;
- `forecast_start_cents` uses available for a fresh linked liquid account when present, otherwise current with `quality=estimated_current_fallback`; manual accounts use user-attested current and `quality=manual`;
- credit available is borrowing capacity and is excluded from cash/S2S;
- investment cash, restricted/HSA/EBT, non-USD, unknown type, stale linked balances, and liabilities are excluded from near-term cash and listed in `exclusions` with reason codes;
- no FX conversion in v0.1. A mixed-currency user sees per-currency totals and an unsupported consolidated state.

### Universal response envelope

Every user-visible calculated metric returns integer cents and this shape:

```json
{
  "metric": "safe_to_spend",
  "metric_version": "2026-07-23.1",
  "as_of": "2026-07-23T16:00:00Z",
  "reporting_currency": "USD",
  "state": "ready|ready_negative|limited|empty|stale|unsupported|reconciliation_required",
  "value_cents": 84210,
  "components": [
    {"code": "liquid_start", "label": "Cash available now", "signed_cents": 250000, "source_ids": [12], "quality": "fresh_available"}
  ],
  "exclusions": [{"account_id": 14, "reason": "liability_not_cash"}],
  "assumptions": [],
  "freshness": {"oldest_observed_at": "...", "stale_count": 0},
  "reconstruction": {"component_sum_cents": 84210, "unexplained_delta_cents": 0}
}
```

`value_cents` must equal the signed component sum. The server rejects or returns a non-ready state when `unexplained_delta_cents != 0`; clients never recompute financial math from floats.

### S2S and forecast hierarchy

`safe_to_spend_cents = liquid_start_cents - committed_outflows_cents + included_income_cents - earmarks_cents - goal_pace_cents - buffer_floor_cents`.

Every component is separately inspectable. Pending transactions already represented in `available` must be deduplicated from scheduled obligations by stable source/transaction identity; when identity is insufficient, state becomes `limited` and the uncertainty is disclosed. S2S is labeled **“Available to use under these settings”**, never “your balance” or a guarantee.

Forecast uses the same `forecast_start_cents` and the same signed event projection. The UI hierarchy is: decision answer → current S2S → central-path lowest balance → simulated low-point range → data quality/assumptions. A trough band is a distribution of per-path minima, not a date-by-date confidence interval.

Negative S2S is a first-class `ready_negative` result, not clamped to zero and not stamped “On Track.” Daily spend guidance is absent when the numerator is negative. Any utilization gauge must use signed components from the same `as_of` and `horizon_end` and disclose its numerator and denominator; otherwise the gauge is removed. Goal reach uses actual observed contributions or an explicit user-set monthly pace. If neither exists it returns `unknown_pace`; changing only the target date must not produce a self-fulfilling reach date.

The “signed event ledger” is a **pure projection**, not a new database ledger: adapt existing posted `Expense` rows to negative events and `Income` rows to positive events, carry recurrence and stable source identity, and derive import authority by joining existing `import_row_id → ImportRow → ImportSession`. Pending import rows already live outside Expense/Income and remain excluded. Add a persisted sidecar only if a written schema spike proves an event cannot be represented or traced through these existing fields.

### Sparse-data states

- No accounts: `empty`, with demo/manual/import choices.
- Manual balance only: deterministic scheduled projection allowed, stochastic evidence withheld and marked `manual`.
- Under 60 days or fewer than 30 eligible discretionary transaction days: central scheduled path only; stochastic state `insufficient_history`.
- A zero-variance residual pool or fewer than two distinct eligible residual blocks: deterministic path only with `insufficient_variation`; never show 300 identical paths, a probability, or an interval.
- Stale linked balance: show last observed fact and age; block “safe” language.
- Unsupported/mixed currency: show separate facts; do not consolidate.
- Unreviewed import: excluded from analytics.
- Reconciled, committed import: included with `authority=reconciled_statement`.

## 7. Dependency-gated build phases

Acceptance gates, not calendar dates, control promotion. Design spikes, fixtures, and other non-dependent preparation may overlap the target windows below, but a dependent read path is not enabled until its prerequisite gate is green. A missed window moves later work; it never weakens a gate. Migrations are forward-only on user data: rehearse backup/restore and old-image compatibility, never use a down migration as rollback. Tax stays disabled throughout.

### Phase 0 — claim, demo, and release truth (days 1–5)

**Modules:** `README.md`, `PRODUCT.md`, `.env.example`, `server/src/settings.py`, a first-boot secret helper/entrypoint, `server/src/services/demo_readiness.py`, `server/src/routers/auth.py`, `server/scripts/seed_demo.py`, `server/tests/test_demo_mode.py`, `server/tests/test_demo_seed_contract.py`, `.github/workflows/ci.yml`, `client/src/pages/Landing/**`, `client/src/pages/Login/Login.tsx`.

**Dependencies:** no new runtime dependency. Phase 0 is the gate for every later phase.

**Work:**

- Replace prediction/calibration/uniqueness/proprietary-data language with the promise in this plan. Expose a generated feature-status table: `core`, `optional`, `experimental`, `disabled`.
- Remove Tax from landing/demo claims while disabled; keep `/tax` returning a clear unavailable state and out of navigation.
- Make **zero external key** startup a hard contract. On first boot the local entrypoint creates and persists a mode-0600 instance secret without printing it; subsequent boots reuse it. Give the JWT algorithm a safe built-in default, and make `groq_api_key`, `tavily_api_key`, and Plaid credentials optional empty settings. With SQLite and no external credentials, signup/login, manual accounts and transactions, the deterministic structured-CSV path added in Phase 2, S2S, deterministic forecast, scenarios, backup, and export work. Image/PDF/free-text statement extraction, receipt vision, the Clerk, web search, and bank sync are optional Groq/Tavily/Plaid surfaces and visibly disabled when unconfigured; do not call them “offline core.”
- Publish an unauthenticated capability response for `registration_open`, `demo`, `plaid`, `assistant`, `web_search`, and `unstructured_import`. Hide the Sign Up tab when registration is closed and show operator-facing owner/login guidance; never invite a form submission the server is guaranteed to reject.
- Mark all landing financial examples “Illustrative sample,” remove claims that the client-only simulation is the production engine, and either generate vignette values from one canonical fixture or test every displayed equation. Correct the current S2S vignette (`$3,500 − $1,200 + $1,800 − $1,100 − $500 = $2,500`, not `$850`). Remove all Tax/filing scenes and copy while Tax is disabled.
- Replace the demo’s obvious `$1,800` subtraction with a realistic borderline fixture: a purchase date near a scheduled obligation, at least two plausible alternatives (delay/reduce/cancel another recurring cost), and one outcome that changes the recommended action or first-shortfall state. If the fixture has insufficient stochastic variation, show only its deterministic result rather than `0 of 300`.
- Add CI job `release-smoke`: migrate an empty SQLite DB, seed demo, run `assess_demo_readiness`, boot server/container, call `/api/demo-status/` and `/api/demo-login/`, then visit `/`, `/welcome`, `/login`, `/forecast`, and an unknown route.
- Build demo DB during the release, never copy a developer’s stale `.demo` artifact. Keep fail-closed checks and show reason-specific, user-safe status.
- Add a minimal public/authenticated catch-all and preserve a same-origin `next` deep link now; Phase 3 completes its semantic and accessibility treatment. Unknown or signed-out routes must never resolve to a blank application shell.
- Derive README test badges/counts from CI, not hand-written numbers.

**Tests:** `server/tests/test_zero_external_key_startup.py`; restart test proving the generated secret persists; settings-import test with Groq/Tavily/Plaid absent; existing demo mode/seed contracts; capability/signup-closed browser test; canonical landing-equation test; demo borderline-decision golden fixture; frontend copy assertions for forbidden claims and disabled Tax; container smoke with all optional keys unset; browser tests for demo login, disabled bank/assistant/unstructured-import controls, and release routes.

**Acceptance:** a fresh clone starts with no `.env` and no external service key; the generated instance secret survives restart; the core journey makes no Groq, Tavily, Plaid, or other external inference/network call; demo readiness is `ready` after release build; no enabled control requires a missing service; closed registration exposes no Sign Up affordance; every landing equation reconstructs; the demo presents a borderline decision whose timing or alternative changes a useful answer; landing and README make no unsupported outcome or availability claim; screenshots 29/30/31/35/36 can no longer be reproduced as dead ends.

**Rollout/rollback:** copy and CI always active. Demo deployment promotes only after smoke passes. Roll back image and demo DB together; never relax readiness to make a red demo appear green.

### Phase 1 — normalized account and purpose-specific total semantics (days 4–12)

**Migration:** `server/migrations/versions/20260723_01_account_semantics.py`.

Add nullable subtype, current, available, limit, currency, source, observed-at, semantic-role, and review-state fields to `accounts`. Preserve `accounts.balance` as a compatibility shadow for two releases. Backfill `current_balance_cents=balance`, provenance from `plaid_account_id`, and observed time from the appropriate existing refresh/update field, all with `review_state=legacy_unverified`. Infer a semantic role only for an explicit, tested legacy type mapping; otherwise use `unknown/review_required`. Do not invent Plaid currency, subtype, available balance, or liability sign.

Migration must not brick existing users: after upgrade, show an account-by-account review that preserves the legacy name and balance and asks the user to confirm role/currency for manual or ambiguous accounts; linked accounts may resolve through a successful Plaid refresh. Until review, preserved legacy values remain visible as `limited` facts, never disappear into `$0`, and never receive “safe” language. The compatibility reader remains available for the review screen and old image. Add checks for exclusive ISO/unofficial currency and accepted enums. Update PostgreSQL RLS parity if a side table is ever justified.

Before creating the revision, run `alembic heads`; set its `down_revision` to the sole deployed head and fail the branch if multiple heads exist. This is the only planned v0.1 schema migration; any additional migration requires its own ADR and gate.

**Modules:** `server/src/db/models.py`, `server/src/domain/money_metrics.py`, `server/src/services/account_semantics.py`, `server/src/services/plaid_service.py`, `server/src/routers/plaid.py`, `server/src/routers/accounts.py`, `server/src/services/{spend_service,forecast_service,networth_service,forecast_evidence_service,demo_readiness}.py`, `server/src/routers/{accounts,networth,forecast}.py`, `client/src/types/index.ts`, `client/src/pages/Accounts/Accounts.tsx`, `client/src/pages/Overview/Overview.tsx`, and `client/src/pages/Forecast/Forecast.tsx`.

**Dependencies:** Phase 0; no new runtime package. Use existing Pydantic, SQLAlchemy, `Decimal`, and integer-cent helpers.

**Contract:** add `GET /api/accounts/summary/?purpose=net_worth|near_term_cash|forecast` returning the universal envelope. Plaid exchange and refresh persist raw current/available/type/subtype/currency and observation time. Manual account creation requires an explicit type, role, and currency—no “Checking/$0” fake default.

**Tests:** table-driven Plaid fixtures for checking, savings, credit card, loan, investment, restricted, null available, negative credit, stale, future timestamp, unknown subtype, and mixed currency; property test `net_worth=assets-liabilities`; API reconstruction tests; forward migration and backup/restore rehearsal on SQLite and PostgreSQL; upgrade a populated legacy database and complete the manual review path without losing displayed balances; old-image compatibility; MCP/REST parity.

**Acceptance:** a $2,000 checking account plus a $500 positive credit-card balance yields $1,500 net worth and $2,000 near-term current cash, never $2,500; an upgraded unknown legacy account remains visible and reviewable rather than becoming `$0`; every displayed total lists inclusions/exclusions/currency/freshness; all old direct sums are removed from user-facing analytics.

**Rollout/rollback:** dual-read shadow comparison logs only metric codes/deltas, never raw money. Enable `normalized_money_metrics` for demo, then reviewed opt-in users, then all. Rollback deploys the prior compatible reader against the forward schema; do not drop columns or down-migrate user data. Restore a pre-upgrade backup only as an explicit whole-database disaster-recovery operation.

### Phase 2 — signed reconstructable projection, reconciliation authority, and sparse states (days 10–22)

**Migration:** none. Do not create a second event ledger or authority sidecar for v0.1. Existing Expense/Income, `plaid_transaction_id`, `import_row_id`, ImportRow, and ImportSession fields already encode sign, source, review boundary, commit, reconciliation result, and idempotency. If implementation discovers a missing fact, stop for a schema ADR and demonstrate why it cannot be derived before adding one additive column.

**Modules:** `server/src/domain/decision_inputs.py`, `server/src/services/{spend_service,forecast_service,recurring_service,reconciliation_service,import_service,read_queries}.py`, `server/src/routers/{imports,forecast,spend}.py`, `server/src/mcp/{tools,vault}.py`, `client/src/pages/{Forecast,Reconcile}/**`, `client/src/components/custom/Overview/SpendCard.tsx`, and `client/src/components/custom/SafeToSpend/SafeToSpend.tsx`.

**Dependencies:** normalized account contract from Phase 1; no new runtime package.

**Work:**

- Create one pure signed event **projection** with `event_id`, `date`, `signed_cents`, `status`, `source`, `authority`, and `recurrence_id`. Adapt posted expenses as negative and income as positive; derive import authority from the existing import join. Forecast and S2S consume the same projection without persisting duplicate money facts.
- Exclude `pending_review`, discarded, duplicate, and exception rows. A commit is idempotent by import-row ID.
- Reconciliation can mark committed rows `reconciled_statement` only when included signed rows reconstruct closing balance. It may update a manual account’s closing balance only through a separate explicit confirmation that displays old/new/as-of values. It never mutates a Plaid account balance.
- Return the universal envelope, sparse-data state, and an exact signed S2S equation. Separate current decision answer from forecast trough visually and semantically.
- Preserve negative S2S in the API and UI. Remove daily-spend and “On Track” language for a negative result. Retain a utilization gauge only if both numerator and denominator come from this same decision horizon; otherwise replace it with the signed amount and component breakdown.
- Replace the `$1` allotment/`$1` spend initial store values with explicit `loading|empty|failed|ready` state. No fallback number may be formatted or animated while a request is unresolved.
- Fix goal reach: derive pace from observed goal contributions/autofund executions or an explicit user setting, compare the resulting date with the target, and return `unknown_pace` otherwise. Add a metamorphic test that moving only the deadline cannot make a previously unknown pace “on track.”
- Give recurring rows explicit burden semantics: `confirmed_burden` includes only active/likely-active rows that meet the history rule; `possible_burden` lists lapsing/dormant/low-probability rows for review. Show last charge, sample count, next expected window, and whether a price change is already reflected. Never silently count a dormant merchant or multiply a current raised amount by the raise again.
- Add a deterministic structured-CSV importer with a user-reviewed column/sign mapping and canonical export schema. It uses no LLM. Keep image/PDF/free-text extraction in the optional Groq capability.
- Collapse zero-variance or insufficient-history simulations to the central scheduled path. Never present hundreds of identical paths as statistical support.
- Keep the evidence pilot immutable and dark; adapt its account snapshot to normalized semantics without rewriting historical origins.

**Tests:** signed round-trip and refund/transfer fixtures; projection parity against existing rows without duplicate storage; available/pending dedup; deterministic CSV mapping and malformed-sign review; import edit/re-review/commit/replay; malicious closing balance; Plaid balance mutation denial; S2S component-sum property including negative results; forecast/S2S same-start and same-horizon invariant; goal-reach non-tautology; active/dormant/price-rise burden fixtures; zero-variance/insufficient-history matrix; RLS cross-user tests.

**Acceptance:** every S2S value, including a negative one, reconstructs to the cent; forecast and S2S use the same eligible starting cash, horizon, and event signs; the UI contains no `$1/$1` financial fallback; no goal reach date is derived from its own deadline; no identical 300-path state is shown; dormant/possible subscriptions are not silently included in confirmed burden; unreviewed imports never affect analytics; reconciled authority is visible; no import can silently change bank truth.

**Rollout/rollback:** shadow old/new S2S for demo and maintainers; require manual review of large deltas by reason bucket. Enable the pure projection behind `reconstructable_decisions`; rollback returns to old readers and leaves the one Phase 1 forward schema intact. There is no duplicated event store to reconcile or remove.

### Phase 3 — first-use, demo, accessibility, and performance (days 15–25)

**Modules:** `client/src/main.tsx`, `client/src/components/layout/{ProtectedRoute,AppShell,Sidebar,SidebarRail,PageHeader}.tsx`, `client/src/components/layout/nav.ts`, `client/src/components/engraving/EmptyState.tsx`, `client/src/pages/{Overview,Accounts,Forecast,Login,Settings}/**`, `client/src/index.css`, `vite.config.ts`, and Playwright first-user scripts under a committed `client/e2e/` directory.

**Dependencies:** Phase 2 response states; add Playwright, `@axe-core/playwright`, and Lighthouse CI as development-only dependencies. Do not add a UI runtime library.

**Work:**

- Add explicit public and authenticated `*` routes. Preserve a signed-out deep link through `?next=` and return after login; show a real 404 with safe destinations for unknown routes.
- On first login show three paths: demo decision, add one manual account, or import/connect. Do not ask about game mode, tax, AI, rules, or every S2S setting before first value.
- Seed no fake balance, income, category, tax rate, goal, or account. An empty user sees honest state-specific setup.
- Use one semantic `h1` per route, ordered headings, landmarks, skip link, visible focus, status announcements, non-color-only chart descriptions, and keyboard-equivalent scenario controls. Refactor `CardTitle` from an unconditional `div` to an explicit semantic element/`asChild` contract; card consumers choose the correct `h2`/`h3` level and decorative labels remain plain text.
- All touch targets are at least 44×44 CSS px. Respect `prefers-reduced-motion`; lazy-load Three/WebGL/game/advanced panels; do not initialize decorative canvases offscreen or in reduced motion.
- Remove the Overview utilization dial unless Phase 2 supplies same-horizon numerator/denominator components. It may not combine current S2S with a different paycheck/month spend period, clamp a negative result, or infer reassurance from missing data.
- Keep the decision workflow primary. Move Almanac, Rules, Reconcile, AI Connections, game surfaces, evidence, and composer under “Tools/Advanced” until data and intent make them relevant.
- Make AI connection copy explicit: optional, scoped, read-only for MCP; assistant edits require confirmation; a third-party model is used only when configured. Show “Not configured” rather than an active-looking setup burden.
- When the Clerk is unconfigured, hide its launcher or label it “Not configured” with setup guidance. When configured but a request fails, preserve the user prompt, classify the state as recoverable, and offer one working Retry action; do not end at a generic assistant bubble. Deterministic money totals remain available outside the Clerk.

**Tests:** axe on every route and state; heading-outline assertion including `CardTitle` consumers; keyboard-only happy path; computed 44×44 target audit including icon/hover actions; 320/375/768/1280 widths; deep-link auth; closed registration; unknown route; zero-data/loading/error without numeric flashes; signed negative S2S; same-horizon gauge contract or gauge absence; assistant unconfigured and retryable failure; stale/limited/unsupported metric states; demo read-only; manifest-based bundle budgets; Lighthouse CI.

**Acceptance:** a nontechnical user reaches a reconstructed decision in under five minutes with demo data or a manual account plus one cash event; no mystery route or blank shell; no false signup or assistant affordance; zero critical axe violations; correct heading outline; all interactive targets are 44px; fixed-profile, five-run median LCP under 2.5s, INP under 200ms, CLS under 0.1 on the core decision route. From the Vite manifest, the entry plus the transitive static-import closure needed for the first decision is ≤250KB gzip JS and ≤350KB gzip total JS+CSS; each lazy advanced/game chunk is ≤200KB gzip; optional chunks may not enter the core static closure. CI prints the measured closure and fails on regression, so “excluding lazy chunks” cannot hide a static import.

**Rollout/rollback:** new onboarding behind `decision_first_onboarding`, tested on demo first. Keep direct URLs to old tools. Rollback flag restores old hierarchy without reverting semantic/a11y fixes.

### Phase 4 — real forecast evidence and naive baselines (days 27–60, then at least six months of observation)

**Migration:** none initially. Represent each predeclared baseline as another immutable `ForecastEvidenceOrigin` cohort with a namespaced `model_version` (for example `baseline:recurring-only:v1`) and the same origin, horizon, input hash, account set, predictions, and realized observation. Include the metric/balance semantic versions in `model_version` and `input_hash`; recompute aggregate evaluations from immutable origins rather than storing mutable score columns. Add schema only after an ADR demonstrates the existing cohort model cannot answer a required query.

**Modules:** `server/src/services/forecast_evidence_service.py`, `server/src/services/forecast_baselines.py`, `server/src/services/forecast_sim.py`, `server/src/scheduler.py`, `server/scripts/forecast_backtest.py`, `client/src/pages/Forecast/ForecastEvidencePanel.tsx`, `docs/FORECAST-BACKTEST.md`.

**Dependencies:** Phase 2 metric/event versions and Phase 3 honest states; use existing NumPy/SciPy stack, adding no new model package.

**Baselines:** compare the model at 7/14/30 days against (A) no-change balance, (B) deterministic recurring-events-only path, and (C) recent daily net-flow mean. Use the same eligible account set, origins, horizons, and once-daily realized trough. Never select a baseline after observing outcomes.

**Metrics:** mature-origin count; distinct-user count; calendar span; eligibility rate and reason distribution; MAE of central trough; interval coverage and mean interval width; Brier score for below-zero event; calibration by probability bin only when each bin has enough examples; relative MAE/Brier improvement over each baseline. A deterministic baseline's below-zero probability is its predeclared 0/1 central-path result. Report a user's local record from that user's own database. Compute a pooled aggregate only from explicit, revocable research opt-in and export only de-identified origin-level errors/eligibility metadata—never accounts, merchants, transaction rows, amounts, or scenario text.

**Evidence gates:**

1. **Local descriptive record:** after the first matured origin, a user may inspect literal outcomes with sample size, dates, horizon, and version. Before 30 matured local origins it receives no “accurate,” “better,” “calibrated,” grade, or promotion label. Local evidence never supports a public population claim.
2. **Engineering beta gate:** at least 100 matured eligible origins across at least 20 consenting users, including at least 30 at the 30-day horizon. This is enough to validate capture, invalidation, reporting, and obvious model failure—not enough for a public superiority claim.
3. **Public pooled claim gate:** at least 300 matured eligible origins across at least 30 consenting users, at least 100 30-day origins, and at least six calendar months between the first and last origin. The primary analysis counts only the predeclared disjoint stream; all eligible origins may appear as a labeled sensitivity analysis. Pre-register the cohort and compare on the same origins. Use a user-cluster bootstrap; the lower 95% confidence bound must exceed 0 for improvement and the point estimate must beat recurring-only MAE by ≥10% at two horizons. Brier is non-inferior only when the upper 95% confidence bound for model-minus-baseline Brier is ≤0.01. Empirical coverage for a nominal 90% interval must be 85–95%, and its mean width may not exceed the recurring-only residual interval's width at the same coverage. If a gate fails, deterministic forecast stays primary and stochastic output remains experimental or is removed.

The 20-user/100-origin gate is an engineering gate; the 30-user/six-month gate is the only gate for public comparative claims. Neither is the 30-onboarding adoption cohort in Section 10.

**Tests:** fixed-origin golden baseline outputs; stable seed repeatability; origin-before-outcome and disjoint-stream leakage guards; immutable first-observation constraint; missing-day/account-set-change invalidation; metric recomputation from stored rows; model-version cohort isolation; empty/low-sample panel copy.

**Acceptance:** origins are future-clean and immutable; missing days/account changes invalidate visibly; baseline and model rows share exactly the same eligible origins; reports reproduce from stored origins; local and pooled evidence are technically and linguistically separated; every public number includes distinct users, origins, calendar span, horizon, version, confidence interval, and evaluation date; no “calibrated” or comparative claim before the public pooled gate.

**Rollout/rollback:** pilot remains default-off, then maintainer opt-in, then explicit user opt-in. Rollback disables capture/display but never deletes evidence. Model version changes create new cohorts, not overwritten history.

### Phase 5 — canonical pure engine and thin adapter pilots (gated hypothesis; days 35–60)

This is a hypothesis, not an architectural commitment: **if one pure engine can accept a small canonical snapshot from three sources without source-specific branches, the app can become an open decision layer rather than another ledger.**

**Modules:** `server/src/engine/{contracts,metrics,events,forecast,scenario}.py` with no SQLAlchemy/FastAPI/Plaid imports; `server/src/adapters/{native,actual,firefly}.py`; `server/src/routers/adapters.py`; `adapters/actual-bridge/{package.json,src/export.ts}`; JSON schemas in `schemas/decision-snapshot-v1.json`.

**Canonical input:** accounts with normalized semantics, signed posted events, recurring events, goals/earmarks, as-of timestamp, currency, source provenance, and quality. **Canonical output:** universal metric envelopes, daily central path, applied/ignored assumptions, trough simulations, and evidence metadata.

**Pilot scope:**

- Actual: the optional Node bridge reads through official `@actual-app/api`; the user supplies server URL, sync ID, and secret to the local process, which emits canonical JSON to stdout for `server/src/adapters/actual.py` to validate. Map ≤2 account types and posted transactions, read-only; never persist credentials.
- Firefly III: read through REST API with a read-only personal access token. Map asset accounts, liabilities, and signed transactions, read-only.
- **Stage A — feasibility only:** import golden fixtures plus one consenting volunteer dataset from each source into an ephemeral canonical snapshot. This may find mapping failures but cannot validate adoption or justify an “open decision layer” claim.
- **Stage B — strategic pilot:** after Stage A passes, recruit at least five consenting users per source (ten total), each with a distinct real dataset. Do not persist third-party credentials or write back. Record setup time, mapped balance/event coverage, unsupported semantics, whether a decision-ready snapshot is produced, and whether the user can explain one changed decision.

**Dependency/gate:** no full extraction until Phases 1–4 contracts are stable. Stage A proceeds only if fixtures have exact native-output parity and no duplicated metric math. A strategic adapter claim or navigation entry requires Stage B: per source, ≥95% of supported balances/events round-trip, unsupported semantics are explicit, at least four of five datasets are decision-ready, and median setup is under 15 minutes without maintainer intervention. If either adapter requires source-specific engine behavior or misses the four-of-five readiness gate, stop at documented canonical import/export and keep the native ledger. A failed adapter hypothesis does not block the core open-source release.

**Dependencies:** optional `@actual-app/api` only inside `adapters/actual-bridge`; existing HTTPX for Firefly REST. Neither enters core install or startup.

**Tests:** golden canonical fixtures; adapter contract suite; malformed/partial source; currency/type mapping; secret redaction; native-vs-engine parity; no adapter network in core tests.

**Rollout/rollback:** experimental CLI/import preview first, no navigation. Adapters are optional extras and never core dependencies. Removal leaves exported canonical JSON valid.

### Phase 6 — open-source distribution, governance, and sustainability (days 45–75)

**Modules/artifacts:** `Dockerfile`, `docker-compose.selfhost.yml`, `.github/workflows/{ci,release}.yml`, `server/src/services/data_export.py`, `server/src/routers/data_export.py`, `server/scripts/{backup,restore}.py`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, `docs/adr/**`, and GitHub issue/PR templates. No schema migration is required unless export audit metadata is later justified; v0.1 should avoid it.

**Artifacts:** MIT license audit, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, architecture decision records, public roadmap, issue/PR templates, reproducible Docker/OCI images with SBOM and provenance, signed tags, migration/backup/restore guide, data export/delete guide, support matrix, release notes, and a public demo privacy notice.

**Dependencies:** completed Phases 0–4. Phase 5 may pass, stop at import/export, or continue after v0.1; it is not a release dependency. Syft/Cosign run in release CI rather than the application image. Core runtime remains unchanged.

**Release contract:** semantic versioning; database backup before migration; support latest two minor versions; deprecation for one minor release; security disclosure SLA; deterministic sample dataset with no real financial data; container health checks; zero-external-key compose with a persistent generated instance secret; optional extras for Plaid/Groq/Tavily/unstructured import/adapters. Measure install success only in a disclosed observed cohort or from voluntary success reports, without mandatory telemetry.

**Governance:** one maintainer may release v0.1, but money-semantic changes require two reviewers or one reviewer plus a published golden-fixture diff. Contributors sign DCO, not a broad CLA, unless future legal advice requires otherwise. Publish metric-contract ADRs and label breaking financial semantics as such.

**Sustainability:** begin donation/sponsor links only after stable releases. A future hosted service may charge for managed updates, encrypted backup, and aggregation convenience while the full decision engine remains MIT. Never sell data, use financial data for model training by default, or gate export. Plaid and third-party inference costs are user-provided or clearly metered.

**Acceptance:** a stranger can install, reach a manual-data decision, back up, upgrade, roll back, and export without contacting the maintainer; release artifacts reproduce from the tag; secrets and real demo data are absent; dependency and container scans are green.

**Tests:** clean-machine compose on Linux; empty and populated backup/restore; forward upgrade from the previous tagged database; old-image/forward-schema compatibility; restore the paired pre-upgrade backup on a disposable copy; full export schema validation; SBOM/signature verification; secret scan; no-external-service core journey; optional-service absence matrix.

**Rollout/rollback:** publish `v0.1.0-rc.1`, hold a seven-day install/upgrade window, then sign `v0.1.0`. Keep the prior image and documented pre-upgrade backup. Prefer the prior compatible image against the forward schema; if incompatible, stop writes and restore the paired backup as a whole. Never down-migrate user data or imply that rolling back an image reverses a financial schema change.

### Tax repair gate — outside v0.1

`tax_features_enabled` remains `false`, the router remains non-navigable, agent tax tools stay unregistered, reminders self-skip, and no demo/landing copy implies tax capability. A later tax release requires: normalized currency/account semantics; explicit tax year and user timezone; provenance from each summary figure to reviewed transactions; separation of organizer facts from estimates/advice; golden fixtures for filing status, quarterly periods, refunds, prior-year tax, and state-rate edge cases; current primary-source review; accessibility and export review; and an independent adversarial sign/rounding audit. Passing ordinary tests is not enough to enable it.

This is a documented correctness block, not quiet postponement. `server/src/services/tax/rates.py` currently labels the 2026 mileage rate and Social Security wage base as placeholders, copies 2025 brackets into 2026, and allows an untabulated-year flat-rate fallback. Those constants/fallbacks must be removed or replaced from dated primary sources with source metadata and effective dates before any Tax route, seed, landing scene, reminder, assistant tool, or release claim can be enabled.

## 8. First 30 days

These are target windows with explicit dependency gates, not promises that partially complete phases may merge. Parallel work is limited to fixtures, copy, and non-dependent UI preparation.

1. **Days 1–5:** freeze feature work; land truthful copy/capability matrix; add zero-external-key and persistent-secret tests; hide closed signup/unconfigured services; keep Tax disabled; correct landing equations; build and smoke the borderline demo; add real 404 and signed-out deep-link preservation.
2. **Days 4–7, preparation only:** finalize the account mapping fixtures, migration ADR, backup/restore rehearsal, and legacy-review prototype. Do not merge the migration until Phase 0 is green.
3. **Days 6–15:** land the single account-semantics migration and purpose-total contract; prove populated legacy upgrade/review and raw Plaid current/available/type/subtype/currency/freshness.
4. **Days 13–23:** after Phase 1 is green, replace direct sums and land the pure signed event projection, deterministic CSV mapping, negative/reconstructable S2S, non-tautological goal reach, recurring-burden semantics, and sparse/zero-variation states. No Phase 2 migration.
5. **Days 20–30:** after Phase 2 response states freeze, finish decision-first onboarding, honest loading/empty/error states, 404/deep links, semantic CardTitle usage, 44px targets, Clerk retry/disabled behavior, reduced motion, lazy advanced surfaces, and measured bundle closure.
6. **Days 27–30:** audit existing evidence origins and implement baseline cohorts only if Phase 3 is green. Evidence collection continues for at least six months; no 30-day public accuracy claim is possible.
7. **By day 30:** run five formative first-use sessions and five observed clean-machine installs, fix release blockers, and decide only whether to continue stabilization. Adapter strategy waits for Phase 4 stability and the five-users-per-source Stage B gate.

## 9. Honest v0.1 definition of done

v0.1 is complete only when all are true:

- A fresh clone starts with a persisted generated instance secret and delivers manual plus deterministic structured-CSV decisions with zero Plaid/Groq/Tavily keys; unstructured import, assistant, web, and bank controls are absent or clearly unconfigured.
- A public, migrated, reseeded, read-only demo completes a realistic borderline decision in which timing or an alternative changes the action—not merely an exact subtraction on a comfortable balance.
- Account current/available/type/subtype/currency/freshness are normalized and every purpose-specific total is correct on the adversarial fixture matrix.
- An upgraded legacy database preserves visible balances and provides a review/migration path; unknown semantics never silently become `$0` or a “safe” answer.
- S2S is signed, including negative state, reconstructable to the cent, uses the decision horizon, and is visually distinguished from forecast trough/range; a utilization gauge is same-horizon and reconstructable or absent.
- Unreviewed imports are excluded; committed reconciled data has visible authority; Plaid balances cannot be changed by an import.
- Goal reach uses independent observed/configured pace or says unknown; recurring burden separates likely active from possible/dormant; price changes are counted once.
- Sparse, zero-variation, stale, unsupported, and mixed-currency states are honest; no identical-path probability, `$1/$1`, or other fake financial default appears.
- Forecast output is labeled modeled/directional. Evidence is either empty/experimental with sample size or passes the published baseline gate.
- Demo, signup capability, Clerk recovery/disabled state, deep links, 404s, semantic CardTitle/headings, keyboard use, 44px targets, reduced motion, and explicit bundle/performance budgets pass automated and manual checks.
- Every landing money example reconstructs and is labeled illustrative unless generated from the production contract.
- AI/MCP are optional and accurately described; the core makes no external inference or aggregation call.
- Tax is disabled and absent from the release promise; known placeholder rates are recorded as blockers.
- Docker image, migrations, backup/restore, full export, security policy, contribution guide, SBOM, signed release, and reproducible sample dataset ship from the public tag.
- The first five formative sessions have no unresolved severity-1 first-use blocker, then an independent validation cohort has at least eight of ten target users complete the demo decision unaided and explain: the decision answer, main inputs, why S2S and trough differ, and one limitation. The small cohort is a release usability check, not an adoption claim.

## 10. Product, adoption, value, and accuracy scorecard

Collect local analytics only with opt-in; public demo may collect coarse, non-financial events disclosed in its privacy notice. Never collect account names, merchants, amounts, or scenario text.

### Activation and adoption

- Install success: container healthy and first page loaded / all consented, observed beta install attempts; target ≥70%. Do not infer failed attempts from repository traffic or telemetry-free downloads.
- First value: users completing a demo/manual/import decision within 10 minutes; target ≥60%.
- Comprehension: users correctly answer four explanation questions; target ≥80%.
- Week-4 return: activated users completing a second decision in days 8–35; target ≥25% for the narrow early cohort.
- Data health: activated users reaching `ready` or understood `limited`; target ≥70%.
- Open-source health by month 3: ≥10 successful external installs, ≥3 external contributors, issue median first response <7 days, and two on-time patch releases. Stars are awareness, not adoption.

### User value

- Decision completion without help; target ≥80% after activation.
- Median time from opening Forecast to saved/understood answer; target <3 minutes for returning users.
- “Changed or confirmed a real choice” self-report at follow-up; target ≥40%, recorded without the choice or amount.
- Reconstruction use: ≥20% inspect components at least once, but <20% report the breakdown is confusing.
- Trust: ≥80% agree “I know where this number came from”; ≤10% believe it is a guarantee.

### Accuracy and data quality

- Metric reconstruction invariant: 100%; any nonzero unexplained delta is a release blocker.
- Account semantic classification on golden fixtures: 100% expected inclusion/sign/currency.
- Evidence eligibility and invalidation: 100% against fixture matrix.
- Forecast baseline metrics and staged local/engineering/public gates: as specified in Phase 4; never pool local evidence without research opt-in or replace future outcomes with anecdotal screenshots.
- Reconciliation: 100% signed closing-balance reconstruction on reconciled sessions; zero unreviewed rows in analytics.

### Kill or pivot criteria

- **Correctness kill:** any repeatable liability-as-cash, cross-currency sum, unreviewed-import inclusion, or silent Plaid balance mutation pauses release immediately.
- **Prediction kill:** at the public pooled gate (30 users, 300 eligible origins, 100 at 30 days, six months), the stochastic model fails the pre-registered confidence-bound/MAE/Brier/coverage-width criteria; remove stochastic prominence and public comparative claims, and ship deterministic decision planning only. Reaching the 20-user engineering gate alone cannot trigger a positive accuracy claim.
- **Adoption kill:** after 30 observed target-user onboardings, <30% reach first value or <15% return by week 4 despite fixing identified usability blockers; stop breadth work and test a read-only decision layer on Actual/Firefly instead.
- **Self-host kill:** after 20 observed technical installs, <50% succeed without maintainer help; pause adapter/product expansion and fix packaging.
- **Comprehension kill:** >20% of tested users interpret S2S or the range as a guarantee; remove the disputed metric from the hero until copy/visual hierarchy tests pass.
- **Sustainability kill:** maintainer support exceeds 8 hours/week before 25 weekly active installs; reduce supported configurations and feature surface rather than accepting unsafe maintenance debt.

These denominators answer different questions: 20 users/100 origins is evidence-pipeline engineering; 30 users/300 origins/six months is pooled forecast evidence; 30 target-user onboardings is adoption; 20 technical installs is packaging. Report them as separate cohorts even if some people overlap.

## 11. Risks and non-goals

### Principal risks

- Bank data are stale, inconsistent, and institution-dependent; freshness and provenance must remain visible.
- Self-hosting reduces distribution and increases support burden; ProjectionLab’s 0.6% self-host usage is a warning.
- Forecast evidence will be sparse and selected toward engaged users; pooled results may not generalize.
- Open adapters can broaden semantics faster than the engine can safely model them.
- The current decorative/game surface can dominate bundle size and product meaning.
- A public demo handling financial examples can be mistaken for a production service unless isolated and labeled.
- Licensing code does not license third-party bank/AI services or their data.

### Non-goals for v0.1

- Guaranteed predictions, personalized financial/investment/tax/legal advice, tax filing, money movement, credit underwriting, product recommendations, or automated autonomous actions.
- Household permissions, advisor tenancy, multi-user hosting, global FX conversion, full multi-currency planning, mobile native apps, or parity with Monarch/Quicken.
- Replacing Actual or Firefly as a ledger, or ProjectionLab as a retirement planner.
- Training a proprietary model, pooling user financial data by default, or creating a data moat.
- Full engine extraction before native correctness and thin adapter pilots pass their gates.

The vision succeeds if it becomes the clearest inspectable place to answer a real near-term money question. It fails if it becomes a broad dashboard with impressive statistics whose inputs, meaning, and evidence a first-time user cannot explain.
