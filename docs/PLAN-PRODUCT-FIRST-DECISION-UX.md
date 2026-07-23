# Product-first decision UX — build plan

**Branch:** `feat/product-first-decision-ux`  
**Baseline:** `feat/verified-decision-foundations`  
**Status:** implemented and verified after three plan reviews and three code-review passes

## 1. Outcome

Make the first useful loop of the product obvious and trustworthy:

> Before I spend this, will I be short before payday—and what assumptions make that answer true?

The build keeps the current engraved-ledger visual identity, routes, and underlying feature set. It changes hierarchy, labels, contracts, validation, and trust states so a new user can reach a defensible answer quickly. It does not turn the product into a generic budgeting dashboard.

Success means a first-time user can:

1. see the amount that is safe to use now and the next material cash events;
2. open **Decisions**, enter a purchase or income change, and receive an answer tied to a chosen horizon;
3. distinguish a modeled central path from a range of modeled low points;
4. see rejected or ignored assumptions instead of silently receiving a misleading result;
5. understand that AI connections are optional, scoped, read-only advanced integrations.

## 2. Evidence behind the plan

Research was completed before implementation. The product patterns we will borrow, without copying their visual design, are:

- one-question activation and imported-history setup from Copilot;
- explicit scenario comparison and directional-not-exact language from Monarch Forecasting;
- an upcoming-events review loop from Monarch Recurring and PNC Low Cash Mode;
- literal targets and progress language from YNAB;
- limited, incremental permissions from Google and the MCP authorization guidance;
- keyboard-complete, non-drag alternatives and reduced-motion behavior from WCAG/APG.

The differentiated wedge remains the consolidated, cross-account, short-horizon decision loop. Budgets, goals, subscriptions, net worth, generic insights, and generic chat are supporting tools, not the hero promise. MCP is a secondary distribution channel.

Primary sources:

- [Monarch Forecasting](https://help.monarch.com/hc/en-us/articles/48344305092244-Forecasting-in-Monarch)
- [Monarch Recurring](https://help.monarch.com/hc/en-us/articles/4890751141908-Tracking-Recurring-Expenses-and-Bills)
- [Copilot Quick Start](https://help.copilot.money/en/articles/11157550-quick-start-guide)
- [PNC Low Cash Mode](https://www.pnc.com/en/personal-banking/banking/services/low-cash-mode.html)
- [MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [MCP security guidance](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [Claude Code MCP setup](https://code.claude.com/docs/en/mcp)
- [WCAG dragging alternatives](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html)
- [ARIA slider pattern](https://www.w3.org/WAI/ARIA/apg/patterns/slider/)
- [WCAG reduced motion](https://www.w3.org/WAI/WCAG22/Techniques/css/C39)

## 3. Release boundaries

### In this branch

- correct and simplify the Forecast/What-if contract and UI;
- make the four daily tasks primary in navigation and overview hierarchy;
- remove the mandatory self-employed fork from the first-use path;
- harden transfer suggestions so coincidences are not stated as facts;
- make MCP connection states, duration, permissions, setup instructions, and audit failures truthful;
- replace the public MCP availability claim with truthful static integration copy;
- put essential landing copy before the decorative crest on mobile;
- add backend, component, accessibility, and browser regression coverage.

### Explicitly out of scope

- OAuth/PKCE and consumer Claude/ChatGPT connector interoperability;
- money movement or automatic transfer execution;
- a new account-aggregation provider;
- a new design system, route migration, or page rewrite;
- deleting budgets, goals, tax, game mode, reconciliation, or other existing tools;
- claiming real-world calibration until observed forecast outcomes support it;
- changing financial data or production deployment settings.

OAuth is a separate security epic because it requires authorization-server discovery, protected-resource metadata, PKCE, audience-bound tokens, refresh-token rotation, revocation, incremental consent, and interoperability testing.

## 4. Workstream A — one authoritative Decision contract (P0)

### A1. Server forecast and scenario semantics

Touch:

- `server/src/services/forecast_service.py`
- `server/src/services/scenario_service.py`
- `server/src/services/scenario_overlay.py`
- `server/src/services/forecast_sim.py`
- `server/src/routers/forecast.py`
- `server/src/routers/scenarios.py`

Implement:

- Produce a daily baseline timeline from horizon start through horizon end and a separate `events` array for scheduled income/expense metadata.
- Keep compact metrics in `baseline.result` and `scenario.result`. Return top-level `baseline_timeline`, `scenario_timeline`, `baseline_events`, and `scenario_events` only from the ad-hoc/saved **evaluate** responses. Do not add these series to compare columns, committed-plan snapshots, or drift checks.
- Return `horizon_start`, `horizon_end`, `first_negative_date`, `applied_changes`, and `ignored_changes` with stable reason codes.
- Use the chosen 30/60/90/365-day horizon everywhere. Scenario evaluation must not fall back to 90 days when the page displays another horizon.
- Retain numeric, horizon-capped `runway_days` for backward compatibility. Add nullable `first_negative_date`, defined as the first day the modeled balance is below zero; it is not the trough date.
- Include the horizon-end balance even when no scheduled event occurs on that date.
- Make consumer forecast/evaluate calls reproducible with a documented, versioned deterministic simulation seed. Baseline and scenario use the same seed for common-random-number comparison. Do not derive or log a financial-data fingerprint.
- Return `paths_below_zero` and `paths_total` from the simulation and carry them through Forecast and compact Scenario results. Preserve the unrounded invariant `paths_below_zero / paths_total == overdraft_probability`; round only for display.
- Validate fields at the API boundary with type-specific rules: added-recurring and discrete-flow amounts are finite and `> 0`; goal target amounts are `> 0`; goal progress is finite and `>= 0`; a balance override is finite and may be signed; recurrence is from the explicit supported whitelist; dates are valid ISO dates.
- Direct Forecast requests reject `end < start` and spans over 365 days. Point-count acceptance is based on the effective inclusive date span, not an unrelated default-days value.
- Handle flows on `horizon_start` explicitly instead of skipping them in a walk that starts one day later.
- Reject malformed changes with a 422. Preserve well-formed changes outside the chosen horizon in `ignored_changes` with an actionable reason; never silently no-op.
- Give each submitted overlay item a stable response identifier such as `discrete_flow:0` or `added_recurring:1`, without changing the stored overlay schema. Classify nonexistent goals, out-of-window flows, unsupported stored config, and recurring additions with no occurrence inside the horizon.

Acceptance:

- The real API contract—not a frontend fixture—can render baseline and scenario lines.
- Changing the page horizon changes the evaluated scenario horizon.
- A test with an early negative day and a later trough reports the early negative day.
- Repeating a request returns the same modeled percentiles.
- Daily series includes both endpoints and has `horizon_days + 1` points; scheduled events appear separately and horizon-start flows are reflected once.
- Compare, plan snapshots, and drift responses remain compact.
- Each submitted change appears exactly once in applied or ignored output.
- `paths_below_zero / paths_total` equals the unrounded model fraction, and consumer copy renders it as **X of Y modeled paths**.

Response shapes are frozen for this branch:

- Forecast: `timeline`, `events`, `first_negative_date`, `paths_below_zero`, `paths_total`, and existing metrics.
- Evaluate top level: `horizon_start`, `horizon_end`, `baseline_timeline`, `scenario_timeline`, `baseline_events`, `scenario_events`, `applied_changes`, and `ignored_changes`.
- Compact `baseline.result` / `scenario.result`: existing metrics plus `first_negative_date`, both path counts, and trough range; no timeline or events.
- Event: `date`, `income`, `expenses`, `net`, and `label`.
- Compare: compact columns only.

### A2. Client state and validation

Touch:

- `client/src/store/store.ts`
- `client/src/lib/scenario.ts`
- `client/src/components/custom/ScenarioBuilder/ScenarioBuilder.tsx`
- `client/src/pages/Forecast/Forecast.tsx`

Implement:

- Rename the visible destination and page heading from **Forecast** to **Decisions** while retaining the route.
- Make only currently representable presets the first interaction: one-time purchase, one-time income, new recurring expense, and new recurring income. Defer income delay and changes to an existing stream until source selection plus exclude/replace semantics exist. Put the supported raw mutation fields under an **Advanced assumptions** disclosure and remove Config from the builder.
- Add explicit field labels, inline errors, date bounds, and non-drag controls. Amount input is unsigned; direction is expressed by the selected action.
- Replace edit-triggered debounced requests with an explicit **Evaluate decision** action. Track the serialized evaluated overlay plus horizon; changing either marks the answer stale. Disable evaluate while invalid/evaluating and disable save while invalid, stale, or evaluating. Clear stale result emphasis when an assumption changes or the last mutation is removed.
- Pass the selected horizon into every scenario request and comparison.
- Show one answer first: scenario low point, change from baseline, first modeled shortfall date, and number of simulated paths below zero when available.
- List applied and ignored assumptions directly under the answer. An ignored item offers **Extend horizon** when relevant.
- Draw the evaluate-only baseline and scenario daily lines. Update `CashflowCalendar`, projected-obligations lists, and Overview's next-events preview to read the separate `events` contract rather than inferring events from sparse timeline points. Remove the full-width `ReferenceArea` that incorrectly depicts a low-point distribution as uncertainty at every date.
- Present the modeled low-point distribution as a separate compact range/quantile summary with text and a non-color legend.
- Use only `modeled path`, `central path`, `percentile`, `modeled range`, and `directional estimate`. Forbid `confidence`, `chance`, `calibrated`, and probability language in this consumer surface.
- Remove `ForecastEvidencePanel` from the consumer decision path. Keep its data collection and dedicated tests intact for future internal evaluation.
- Move allocation-draft composition below saved decisions in a clearly labeled **Advanced: allocation drafts** section.

Acceptance:

- A user can answer a purchase question without opening advanced controls.
- Keyboard-only users can choose all presets, dates, amounts, horizons, and inspect the result.
- Invalid, stale, loading, ignored, empty, and error states are distinct.
- No visual element implies date-specific uncertainty when the server only returns a distribution of trough values.
- A text summary conveys the same decision as the chart.

## 5. Workstream B — hierarchy before breadth (P1)

### B1. Navigation

Touch:

- `client/src/components/layout/nav.ts`
- `client/src/components/layout/SidebarRail.tsx`
- `client/src/components/layout/Sidebar.tsx`
- all three `client/src/terms/terms.*.json` catalogs
- page headings, `NavPalette`, `CommandDeck`, and their tests

Implement:

- Put four persistent, labeled primary destinations first: **Overview**, **Decisions**, **Upcoming**, **Transactions**.
- Map these to existing routes. Rename visible labels only: Forecast → Decisions, Standing Orders/Subscriptions → Upcoming, Ledger → Transactions, Almanac → Insights, Reconciliation Desk → Import & reconcile.
- Group the remaining tools under visually quieter **Plan**, **Review**, and **More** sections. Do not remove their routes.
- Desktop navigation remains labeled without requiring hover. Mobile preserves the existing drawer but uses the same groups and labels.
- Add active, hover, focus-visible, and collapsed semantics. If a compact mode remains, persist the user choice; never make hover the only way to discover labels.

Acceptance:

- The four primary labels are visible at 1280px without hover.
- Every destination remains reachable.
- Active destination and focus are programmatically exposed.
- No primary touch target is smaller than 44px.

### B2. Overview and first-use path

Touch:

- `client/src/pages/Overview/Overview.tsx`
- `client/src/components/custom/Overview/SpendCard.tsx`
- `client/src/components/custom/Overview/ForecastCard.tsx`
- `client/src/components/custom/Onboarding/SelfEmployedFork.tsx`
- `client/src/components/layout/AppShell.tsx`

Implement:

- Above the fold: safe-to-use answer, next three material events, and one **Test a decision** action.
- Follow with recent transactions and account/goal context. Move Daily Surface, Saga, rank, and narrative cards below the core decision content; do not delete game mode.
- Replace the mandatory self-employed modal with a dismissible, non-modal personalization prompt after the core page is usable. `Not now` persists locally and does not falsely set employment status.
- Explain empty data in outcome terms: connect/import accounts to estimate upcoming obligations and test a decision.
- Keep copy literal; ledger/game terminology can remain as secondary flavor, not the only task label.

Acceptance:

- A fresh user can navigate and inspect demo/empty states without answering an employment question.
- The decision CTA is visible in the first viewport on desktop and common mobile sizes.
- Dismissing the personalization prompt survives reload without mutating employment data.

### B3. Landing mobile order and truthful MCP copy

Touch the existing landing hero/animation components only as needed.

Implement:

- Preserve the existing independently lazy-loaded coin/3D implementation.
- On mobile, render the headline, core promise, and primary CTA before the decorative crest, or materially shrink the crest and its top spacing so the copy is visible in the first viewport.
- Keep the existing reduced-motion behavior and confirm the copy does not depend on camera choreography.
- Keep MCP below the core decision story. Remove **Available now** and any public issuance CTA; present it statically as an advanced integration whose availability is confirmed after sign-in.

Acceptance:

- With JavaScript animation delayed or reduced motion enabled, meaningful hero content and CTA remain visible.
- No content layout shift is caused by the decorative enhancement loading.

## 6. Workstream C — evidence before automation (P0/P1)

### C1. Conservative transfer suggestions

Touch:

- `server/src/services/matching.py`
- notification/reconciliation copy at the caller that presents matches
- matching and router tests

Implement:

- Add optional category to `MatchRow` and populate it from the Detangler query.
- Equal/opposite amount, different accounts, and a date window are necessary but not sufficient. Emit a transfer suggestion only when at least one normalized title or category has an explicit transfer marker (for example transfer, own-account transfer, or ACH transfer), with exclusions for ordinary purchases.
- Evaluate same-merchant refund evidence before transfer classification.
- Low-evidence equal/opposite pairs produce no transfer notification. Do not invent confidence tiers, linking, or a confirm/reject workflow in this branch.
- Notification copy says what was observed—amount, direction, date gap, and transfer marker—and asks the user to review it. It never says the app moved money, linked records, or proved a transfer.

Acceptance:

- An unrelated Comcast debit and Amazon credit of the same amount across accounts is not classified as a transfer.
- A clearly labeled transfer pair still matches.
- Existing reversible merchant behavior remains intact.

### C2. MCP / AI connections truthfulness

Touch:

- `server/src/routers/mcp_keys.py`
- `server/src/services/mcp_key_service.py`
- `server/src/services/mcp_audit_store.py` and audit response models if needed
- `client/src/components/custom/AgentKeys/*`
- `client/src/pages/Settings/Settings.tsx`
- `client/src/pages/Landing/sections/AgentReadingRoom.tsx`

Implement:

- Label the settings area **AI connections** and the present key flow **Claude Code / developer connection**. Do not claim consumer Claude Desktop or ChatGPT compatibility.
- Generate current Claude Code setup with an explicit HTTP transport (`"type": "http"`) and header credentials, or the documented CLI command.
- Remove **No expiry**. Validate `ttl_days` as an integer from 1 through 365 at the router and service boundaries.
- Derive the Granted summary from actual scopes. Use native checkbox/radio semantics and expose selected duration programmatically.
- Use a focus-contained Radix dialog for the one-time secret. Focus the secret/copy instruction, prevent backdrop and Escape dismissal, and return focus to the create action.
- Fail closed: settings loading/error/disabled states never reveal key issuance. When MCP is disabled, POST creation returns an explicit disabled response.
- Even when disabled, authenticated owners can list and revoke existing keys and inspect audit history.
- Audit errors render **Could not load activity** with Retry, not **No reads recorded**. Copy promises only recorded authorized and scope-denied calls, not every attempt. Audit-name attribution is deferred because it requires an audit schema/lookup decision.
- Replace the privacy claim with: a connected provider may copy data returned under selected permissions; revocation prevents future access but cannot delete copies already received.
- Do not add a public capabilities endpoint. Landing describes the integration without an availability promise or issuance CTA; authenticated `/settings/` remains authoritative.

Acceptance:

- Generated Claude Code configuration validates against current documented shape.
- Null, zero, negative, fractional, and >365 TTL values fail; 1 and 365 succeed.
- Disabled or unknown capability state cannot create a key.
- Existing keys remain revocable while the read surface is disabled.
- Scope summary exactly matches the chosen scopes.
- The secret cannot be lost via accidental backdrop click.
- Landing contains no dynamic availability state to fail open.

## 7. Test and verification matrix

### Backend

- forecast daily balance timeline plus separate events, horizon-start flows, deterministic repeat, horizon propagation, first shortfall, endpoint balance;
- scenario applied/ignored partition and 422 validation;
- transfer false-positive and true-positive fixtures;
- MCP TTL boundary/property tests, disabled creation, list/revoke while disabled, and audit loading/error/retry contract;
- full existing server suite, with failures categorized as introduced vs baseline.

### Frontend

- decision quick paths, invalid/stale/loading/error states, applied/ignored list, horizon propagation;
- forbidden-copy guard for probability/calibration language;
- navigation labels/groups/active semantics across all term catalogs, page headings, palette, and command deck;
- non-blocking personalization and persisted dismissal;
- AI connections loading/error/disabled/ready states, actual granted scopes, duration semantics, focus lifecycle, valid setup snippet;
- landing mobile copy order, truthful static MCP wording, and reduced-motion behavior;
- existing client test suite and production build.

### Browser acceptance

Test the real application, not only fixtures:

- desktop 1440×900: overview → decision → purchase → evaluate → extend horizon;
- mobile 390×844: immediate landing content, drawer labels, decision form without horizontal scroll;
- keyboard only: navigation, disclosure, form, result details, AI-key creation/reveal/revoke;
- reduced motion: no delayed content or camera-dependent reveal;
- forced error states for forecast, settings, MCP activity, and key creation;
- visual comparison in light/dark modes while preserving the engraved-ledger identity.

## 8. Build sequence and review gates

1. Add failing contract tests for A1, C1, and C2.
2. Implement server contracts and migrations only if an additive field requires them.
3. Update client store/types and Decision UI against real responses.
4. Implement navigation, overview, and onboarding hierarchy.
5. Harden authenticated AI-connection states and static landing MCP wording.
6. Add component/a11y tests and run focused suites after each workstream.
7. Run full server and client suites plus production build.
8. Run desktop/mobile/keyboard/reduced-motion browser acceptance.
9. Have a separate adversarial reviewer inspect the diff for financial truth, accessibility, false claims, scope creep, and regressions.
10. Resolve every P0/P1 finding, re-run affected and full suites, then commit and push this branch only.

## 9. Stop-ship rules

Do not ship this branch if any of the following remains true:

- the UI displays a horizon the server did not use;
- an input is silently ignored;
- a scenario line is produced only by test fixtures;
- a low-point distribution is drawn as per-date uncertainty;
- a coincidental equal/opposite pair is asserted to be a transfer;
- MCP key creation is visible or callable in an unknown/disabled state;
- setup instructions name an unsupported client or generate invalid configuration;
- core content depends on motion, WebGL, hover, or drag;
- a new first-use blocker is introduced;
- main or `feat/verified-decision-foundations` is modified.
