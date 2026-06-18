# persFin Analytical Layer — Build Roadmap (Top 3 Differentiators)

> **Audience:** a fresh coding agent with working knowledge of this repo.
> **Source:** distilled from `research/technical-differentiation-roadmap-2026-06-12.md` (the deep-research synthesis) and re-grounded against the *actual code* as of 2026-06-17 (HEAD on `main` after the Tier 4 merge). Where the research and the code disagree, **the code wins** — the research was written without reading it, and several pieces it calls "to build" already exist.
> **Scope:** the three "impressiveness-per-unit-effort" features — **F1 Probabilistic Safe-to-Spend**, **F2 Merchant Lifecycle Engine**, **F3 Nightly Auditor**. Quick-wins (CSV import, embeddings, NL→rules) and the resilience tier (SimpleFIN, PDF ingest) live in the source roadmap; they are the *data-depth* that makes these models sharper and are referenced where relevant, not specified here.

---

## 0. The thesis — why this is the moat

The entire post-Mint market competes on **plumbing** (sync reliability, categorization). The analytical layer — *"what will my money do next, and how sure are you?"* — is near-empty: a 40+ app survey found balance forecasting "lacks implementation across platforms," and even the cohort's "serious AI" apps (Copilot) ship correction-learning categorization, not forecasting.

The industry's most credible AI player validates persFin's exact architecture: **Cleo 3.0 routes all precise computation through deterministic tools and restricts the LLM to interpreting and narrating** — "this eliminates a major source of hallucinations." persFin already has the **deterministic compute layer** (the forecast/scenario engine) and the **LLM-narration layer** (the assistant + Chronicler, both firewalled). What's missing is the **probabilistic middle**: rigorous statistical models whose calibrated outputs the LLM narrates and never fabricates.

These three features complete that middle and surface it across every screen. **The differentiator is not any one model — it is a coherent calibrated analytical layer that is honest about its own uncertainty.** That honesty (a coverage-guaranteed band, a "probability alive," a regime-shift date) is the thing an LLM physically cannot produce on its own, and the thing no competitor ships.

The non-negotiable law that makes it safe (and the reason it's a moat, not a liability): **detectors and models do the math; the LLM only narrates the numbers they hand it, behind the firewall; any action goes through propose→confirm; no real money ever moves.**

---

## 1. What's already true (read this before estimating effort)

The roadmap reads as *completion*, not greenfield. Verified in code:

**F1 — the probabilistic forecast already exists.**
- `server/src/services/forecast_sim.py` `bootstrap_overdraft()` runs a **300-sample moving-block residual bootstrap** (block size `settings.sim_block_days`, default 7) over historical daily-spend deviations. It already emits `overdraft_probability` (fraction of simulated paths whose trough < 0) and `trough_band` (5th / 50th / 95th percentiles of the trough).
- The "burn" model is principled: `forecast_service._discretionary_burn_cents()` is a HistAvg estimator (30-day window, drop the top 10% of charges, divide by window-days), and `_burn_residual_pool_cents()` builds the per-day deviation pool the bootstrap resamples.
- It's a **single choke point**: `bootstrap_overdraft()` is reached by the forecast (`routers/forecast.py`), Safe-to-Spend (`spend_service.safe_to_spend(include_outlook=True)`), and every scenario column (`scenario_service`). Calibrate it once, and all three improve.
- It's already **backtested**: `docs/FORECAST-BACKTEST.md` runs a rolling-origin backtest, finds block-bootstrap honestly corrects for autocorrelation (coverage ~0.55–0.66 vs a 0.90 target), labels the band "estimate, not guarantee," and **explicitly names "conformal (ACI) wrapper" as future work and non-stationarity (regime shift) as the weakness.** F1 is the doc telling us what to do.
- The sim is deliberately **stdlib-only** (`random`, `statistics`) and **seeded** for determinism. Honor both.

**F3 — the entire job + notification + narration infrastructure exists.**
- `server/src/scheduler.py` `build_scheduler()` registers APScheduler cron jobs (`game_monthly`, `game_weekly`, `plan_drift`, `detangle`, `tax_quarterly_reminder`) via a uniform pattern: a pure `job_*(db, now)` function → an async `_*_tick()` wrapper → `_run_in_own_session()` (its own `SessionLocal`, commit/rollback) → `scheduler.add_job(... CronTrigger ...)`. Tests drive jobs directly through the `run_due_game_jobs(db, now)` hook with `settings.scheduler_enabled=False`. **A nightly Auditor is one more job in this exact shape.**
- Notifications are idempotent: `notification_service._add_if_new()` dedups on a stable `ref` (e.g. `budget_overrun:Food:2026-05`). The detectors already exist: `is_anomalous()` (charge-level: ≥3× median **and** mean+3σ), `_generate_budget_overruns()`, `detangle_service.run()` (duplicate/transfer/refund pairing via `matching.py`, ±5-day window), `scenario_service.check_drift()` (plan forecast-violation: overdraft-prob drift > 0.10, goal slip > 14d).
- The **deterministic-facts → one-LLM-call → firewall → cache** narration pattern is shipped: `game/chronicler.py build_week_fact_sheet()` computes facts (engine only), the LLM narrates them, `game/firewall.py screen_output()` screens the prose, and `LlmCache` stores the result keyed by the fact sheet. **F3's narration reuses this verbatim.**

**F2 — the merchant substrate exists.**
- `categorization_service.normalize_merchant()` is the canonical payee key (lowercase, strip digits/punctuation, collapse whitespace; `"NETFLIX.COM #1234"` → `"netflix com"`).
- `subscription_service.detect_subscriptions()` already groups expenses by that key and classifies cadence by median inter-charge interval with a ±20% amount tolerance. F2 sits directly on this grouping; the BG/NBD model is the genuinely new piece.

**Dependency baseline:** Python 3.11; `numpy` + `pandas` present (pandas direct, numpy transitive). **Absent** (i.e. new deps): `scipy`, `scikit-learn`, `statsforecast`, `MAPIE`, `ruptures`, `pymc`, `pymc-marketing`. `apscheduler`, `langchain_groq`, `plaid-python`, `sqlalchemy` present.

---

## 2. Architecture spine

```
            CONTRACTUAL SKELETON                 PROBABILISTIC MIDDLE                 NARRATION                SURFACES
            (deterministic, exists)              (this roadmap)                       (exists, firewalled)
┌───────────────────────────────┐   ┌─────────────────────────────────────┐   ┌───────────────────┐   ┌──────────────────────┐
│ recurring_service             │   │ F1  forecast_sim.bootstrap_overdraft │   │ assistant_service │   │ Overview SpendCard   │
│   project_cashflows()         │──▶│      + conformal calibration         │──▶│   (the Clerk)     │──▶│ Forecast page band   │
│ income / bills / due dates    │   │      + change-point router (ruptures)│   │ chronicler        │   │ Subscriptions Stamps │
│                               │   │ F2  merchant_lifecycle_service       │   │   (the saga)      │   │ Notifications center │
│ forecast_service (burn)       │   │      BG/NBD probability_alive (PyMC)  │   │ firewall.screen_  │   │ (Tier-4 typed bell)  │
│   HistAvg + residual pool     │   │ F3  audit_service (nightly job)      │   │   output()        │   │ propose→confirm      │
│                               │   │      composes ALL detectors          │   │ → LlmCache        │   │ (ConfirmCard/Bridge) │
└───────────────────────────────┘   └─────────────────────────────────────┘   └───────────────────┘   └──────────────────────┘
        already shipped                  ← the gap this roadmap fills →            already shipped            mostly shipped
```

Read left-to-right: the skeleton is known cashflow, the middle adds calibrated uncertainty + per-merchant lifecycle, F3 runs the whole detector battery nightly and hands a fact sheet to the narration layer, and the surfaces are mostly already built (Tier 4 gave us the typed Notifications center and the propose→confirm cards). **Build order is F1 → F2 → F3**, because F1 upgrades the flagship number on plumbing that already exists, F2 is the headline novelty once the forecast is trustworthy, and F3 ties them together — and F3's nightly job is also what refreshes F2's fitted snapshot.

---

## F1 — Calibrated Safe-to-Spend

**Pain:** #3 — balance forecasting is the largest open gap in the market, and persFin's *own* headline Safe-to-Spend number is currently a point estimate whose uncertainty is computed but hidden from the hero surface.

**The reframe:** the forecast is already probabilistic (§1). F1 is three moves on top of `bootstrap_overdraft()` — **calibrate it, keep it honest under regime shifts, and surface it everywhere.**

### Move 1 — Calibrate (split / adaptive conformal)
Today `trough_band` is raw empirical percentiles of bootstrap troughs; the backtest shows they *under-cover* (~0.55 at a 0.90 target). Wrap them in **split-conformal** calibration: hold out a calibration tail of the residual history, compute nonconformity scores (realized trough vs. predicted band) on it, and widen the band by the conformal quantile so coverage meets the nominal level with a finite-sample guarantee. This is a residual-quantile correction — **implementable in `numpy`/stdlib; `MAPIE` is optional**, and the sim's deliberate no-heavy-deps stance is preserved.

- **Where:** add the calibration step inside `forecast_sim.bootstrap_overdraft()` (the single choke point), reading the same residual pool `forecast_service` already builds. Keep the seeded `random.Random` signature so determinism and the scenario seeding (`scenario_service`) are untouched.
- **Output contract is unchanged** (`overdraft_probability`, `trough_band`), so `routers/forecast.py`, `spend_service`, and `scenario_service` keep working — they just get calibrated numbers. Optionally add a `coverage_level` field so the UI can say "90%".

### Move 2 — The stationarity router (the honest, astounding piece)
Split-conformal is only valid on stationary series; the verified failure mode is **distribution shift** — under an abrupt mean shift, coverage decays 0.90 → ~0.84. The fix at the *same compute cost*: run **change-point detection on the burn/category series** (`ruptures`/PELT, or a stdlib CUSUM if we want zero new deps), and **route**: stable regime → cheap split-conformal over the full window; post-shift → weighted-conformal (exponential decay) and/or truncate the training window to the current regime. This is exactly what `docs/FORECAST-BACKTEST.md` flagged as the open weakness.

The router pays a second dividend: the change-point itself is a **user-facing insight** — *"your grocery spending shifted around Mar 3, +$180/mo"* — which feeds F3's Auditor and the game layer's Grace trigger (`weathered_hard_stretch` in the chronicler fact sheet).

- **Where:** a small `forecast_changepoint.py` service consumed by `forecast_sim`; expose the detected regimes so F3 and the game can read them.
- **New dep:** `ruptures` (verified-maintained, BSD-2, ~pure Python, short single-user series are its home turf). A stdlib CUSUM is the zero-dep fallback if we want to hold the line.

### Move 3 — Surface it everywhere
The band is computed but only the Forecast page's *scenario* view renders it. Make uncertainty the headline:
- **`components/custom/Overview/SpendCard.tsx`** — today shows only `s2s.available`. Add the band as the number's confidence: *"90% chance you stay above $X · P(overdraft) N%"*, sourced from `s2s.trough_band` / `s2s.overdraft_probability` (already on the payload). Use `Figure` for the sub-stats and `Stamp` for the risk tier; keep the `.figure`/`.ledger-figures` sober (color law).
- **`pages/Forecast/Forecast.tsx`** — already draws `trough_band` as a `ReferenceArea` and overdraft as a `Stamp` for scenarios. Extend to the **baseline** projection and render the conformal band with `lib/chart.ts` `hatch()` (the steel-engraving fill) so it reads as an engraved confidence corridor, not a flat gradient.
- **Narration:** the Clerk narrates the band on request — *"You're very likely fine; the one tight day is rent on the 3rd, where there's about a 12% chance of dipping below zero."* Numbers come from the engine; the LLM only phrases them.

**New deps:** `ruptures` (optional: `MAPIE`). **Files:** `forecast_sim.py`, `forecast_service.py`, NEW `forecast_changepoint.py`, `routers/forecast.py`/`spend.py` (only if adding `coverage_level`), `docs/FORECAST-BACKTEST.md` (extend), client `SpendCard.tsx` / `Forecast.tsx` / `lib/chart.ts`.

**Definition of done + test hook:** the extended `FORECAST-BACKTEST.md` rolling-origin harness shows calibrated coverage ≥ the empirical-quantile baseline and approaching the 0.90 target on stationary segments, **and** the router holds coverage across an injected mean-shift where plain SCP degrades. Temporal order preserved, no shuffling. Band stays labeled "estimate," not "guarantee," per the existing doc's honesty. Unit tests mirror `test_forecast_sim.py` (determinism under fixed seed, band ordering).

---

## F2 — Merchant Lifecycle Engine (PyMC BG/NBD)

**Pain:** #5 — subscription price-creep and zombie subscriptions go unnoticed; competitors' recurring detection is calendar-pattern-bound and breaks on irregular cadences (28–32-day gym billing, annual renewals). The motivating competitor query: ask the assistant *"did any subscriptions increase this month"* and have it actually know.

**The model:** **PyMC-Marketing BG/NBD, pooled across the user's payees-as-population** — the single-user reframe that *survived* adversarial verification (a lone entity has too little data; the user's hundreds of merchants are the population the hierarchical priors pool over). Per merchant it yields:
- `expected_probability_alive` — the zombie/lapsed-subscription detector.
- `expected_purchases` over a horizon, and `P(zero transactions in next t)` → *"your gym usually bills by now and hasn't."*
- Fit cheaply: **MAP via L-BFGS-B** for the nightly refresh; NUTS for a full posterior when we want credible intervals. Tutorial-scale fits run in seconds.

Pair it with a **deterministic amount-comparison** on recurring merchants for price-creep (*"Netflix went $11.99 → $15.99 this cycle"*) — that comparison needs no ML and must not touch the model.

**Substrate (reuse):** `categorization_service.normalize_merchant()` for the payee key and `subscription_service.detect_subscriptions()` for the per-merchant charge series (dates, amounts, cadence). Subscriptions are computed on read and never persisted — so the model needs a home.

**Persistence:** because the fit is a batch job (seconds, not per-request), **snapshot the outputs.** New ORM model `MerchantLifecycle(user_id, merchant, probability_alive, expected_next_date, last_amount, prev_amount, status, fitted_at)` + an Alembic migration, refreshed by **F3's nightly job** (the natural owner of the periodic fit, on the single-worker invariant). Reads (Subscriptions API, merchant detail) hit the snapshot, never fit inline.

**Surfaces:**
- **`pages/Subscriptions/Subscriptions.tsx`** — a `Stamp` per card: *Likely active* (credit), *May have lapsed* (gold), *Dormant* (debit) — plus *"usually bills ~Jun 22"* from `expected_next_date`. Keep the existing "in 3d / today" badge.
- Optional **`/merchants/:name` detail** — the charge cadence as a `Sparkline`, `probability_alive` as a `Figure`, the price history.
- **Notifications** — add `merchant_lifecycle` and `price_creep` types to the **Tier-4 `NOTICE` registry** in `NotificationBell.tsx` (deep-link `/subscriptions`, gold tone for attention). The Auditor emits them.
- **Narration** — the Clerk narrates the dormant set / price creep from the snapshot: *"Three standing orders look dormant; the $40 gym charge hasn't landed in 45 days, and STREAMVAULT rose $4 this cycle."*

**New deps:** `pymc`, `pymc-marketing` (+ `pytensor`) — the heaviest commitment in this roadmap; gate behind `settings.merchant_lifecycle_enabled` and keep the fit on the single worker. **Files:** NEW `server/src/services/merchant_lifecycle_service.py`, NEW ORM model + migration, `routers/subscriptions.py` (+ lifecycle fields, optional detail route); client `Subscriptions.tsx`, `NotificationBell.tsx` registry, optional merchant-detail page.

**Definition of done + test hook:** a fit-determinism test (fixed seed → stable `probability_alive` within tolerance) on a synthetic payee population with planted active / lapsed / annual merchants; the model must flag a planted zombie (long silence past its cadence) and not flag a healthy monthly payer. Price-creep is a pure-function test (amount comparison). The model output is snapshot-validated, never fit in a request path.

---

## F3 — Nightly Auditor (compose the detectors + narrate)

**Pain:** #5/#6 plus fees/duplicates; market-validated that **proactive beats reactive** (Cleo ships a background Smart Insights Agent; Copilot's proactive nudges are judged "genuinely useful, not annoying"). And self-hosted-tool users explicitly request server-side nightly jobs.

**The job:** a new `job_auditor(db, now)` + `_auditor_tick()` registered in `scheduler.py build_scheduler()` at ~00:50 UTC (after `plan_drift` and `detangle`), in the **exact existing shape** (`_run_in_own_session`, idempotent, `run_due`-testable, `settings.auditor_enabled` gate, single-worker invariant). It is pure composition — **zero LLM in detection:**
1. **Run the detector battery as a batch:** `is_anomalous()` (charge outliers), `_generate_budget_overruns()`, `detangle_service.run()` (dupes/transfers), `scenario_service.check_drift()` (forecast violations), **+ F2's price-creep & zombie-sub from the `MerchantLifecycle` snapshot, + F1's overdraft-probability crossing a threshold** (the calibrated number now means something).
2. **Assemble a deterministic findings fact sheet** in the `chronicler.build_week_fact_sheet()` shape — every number pre-computed by the detectors.
3. **Dedup + rank + cap** — `_add_if_new()` on a stable `ref` (`audit:{kind}:{key}:{period}`) prevents repeat-fire; rank by severity and **cap the nightly batch** (alert-fatigue guard — the reason Cleo paywalls its agent is inference cost; persFin's detector-first design makes the LLM share trivially cheap, but the *user's* attention is the scarce resource).
4. **One Groq call narrates the batch**, screened through `firewall.screen_output()`, cached in `LlmCache`, and written as notifications via `_add_if_new()`.

**Action bridge:** high-value findings become **propose→confirm**, not just notices — a zombie-sub → a `BridgeCard` (*"cancel it in your bank"*, an assisted action that verifies on next sync; no money moves), a forecast violation → a deep-link to Forecast. Reuse `routers/assistant.py` confirm + `ConfirmCard`/`BridgeCard`.

**Surfaces:** the **Tier-4 Notifications center** (`NotificationBell.tsx`) renders the findings as typed, grouped, deep-linked notices — the 60s poll surfaces them with no extra wiring; add the new types to the `NOTICE` registry. Optional: an Overview "Auditor's findings" digest card; optional Chronicler narration surface for the nightly summary.

**New deps:** none (composition). **Files:** NEW `server/src/services/audit_service.py` + the job in `scheduler.py`; reuse `notification_service`, `is_anomalous`, `detangle_service`, `check_drift`, F1/F2 outputs, the chronicler narration pattern, `firewall`; `settings.auditor_enabled`; client `NotificationBell.tsx` registry, optional Overview digest.

**Definition of done + test hook:** a `run_due`-style test (à la `test_game_scheduler.py`) with `scheduler_enabled=False` seeds planted findings (an anomalous charge, an over-budget category, a duplicate pair, a drifted plan, a zombie sub) and asserts: exactly one notification per finding, stable `ref` dedup on re-run, the batch capped, and the narration screened by the firewall. Idempotent and deterministic.

---

## Cross-cutting guardrails (carry across all three)

- **Detector-does-math / LLM-narrates-only.** Every model output passes `firewall.screen_output()` before a human sees it. The LLM never computes a figure it wasn't handed. (Cleo-validated; persFin-enforced.)
- **Propose→confirm for any action.** Auditor suggestions and assisted actions flow through `routers/assistant.py` confirm + `ConfirmCard`/`BridgeCard`. **No real money moves** — Plaid stays read-only; bridges are deduced actions the user executes in their own bank and the app verifies on next sync.
- **Seeded determinism.** Preserve the `random.Random(seed)` discipline in `forecast_sim`/`scenario_service`; F2's fit and F3's job must be reproducible for tests.
- **Single-worker scheduler invariant.** F2's fit and F3's job run once per worker; >1 worker double-fires. Keep one uvicorn worker until leader-election exists (already documented in `scheduler.py`).
- **A `settings.*_enabled` flag per feature** (`merchant_lifecycle_enabled`, `auditor_enabled`; F1 rides the existing `include_burn`/`include_outlook`), default-off in tests.
- **Backtest-before-ship for F1.** No band ships without the `FORECAST-BACKTEST.md` harness beating the empirical-quantile baseline; the band stays labeled "estimate," not "guarantee."
- **Frontend color/figure law.** Money figures stay sober (`.figure`/`.ledger-figures`, `filter:none`); green = in / red = out; gold = attention chrome; never the game amber.

## Build order

```
F1  Calibrate the existing sim  →  add the change-point router  →  surface the band on SpendCard + Forecast baseline
F2  MerchantLifecycle model + snapshot ORM  →  Subscriptions Stamps + notices  →  (fit refreshed by F3)
F3  job_auditor composing all detectors  →  narrate via the chronicler pattern  →  Notifications center + propose→confirm
```

F1 first: it upgrades the flagship number, most of it already exists, and it's the lowest-risk highest-visibility win. F2 next: the headline novelty, and it wants a trustworthy forecast underneath it. F3 last: it ties F1+F2 into one proactive surface **and** owns the periodic fit that refreshes F2's snapshot. This maps to the research's Phase A/B/C, grounded in what's already built.

## Bonus — read-only insight-MCP (strategic follow-on)

persFin's read-only MCP server is no longer unique (Era ships a read-*write* one), but HN sentiment **endorses read-only monitoring and rejects AI write access**. The differentiating move once F1/F2 exist: expose their **model outputs** as read-only MCP tools — forecast bands, `probability_alive`, regime-shift dates — so external agents consume *calibrated quantities* instead of raw rows they'd have to (mis)compute. Nobody does this; competitors' MCP use cases are simple balance/category lookups.

## Risks & open questions

- **PyMC/PyTensor weight (F2).** The heaviest dependency here, against a backend that deliberately keeps its forecast sim stdlib-only. Mitigate: gate behind a flag, run only in the nightly batch (never a request path), MAP-fit for speed. Decision was made to take the full-rigor path; revisit if deploy size/cold-start becomes a problem.
- **Where the fits run.** F2's fit and F3's job both assume the single-worker scheduler; document the precondition and add leader-election before scaling workers.
- **Conformal honesty at small data.** ~30 residual days = few distinct blocks; coverage is "estimate," not "guarantee." The change-point router helps, but the real unlock is **data depth** — F5 CSV import / F8 SimpleFIN / F9 PDF ingest backfill history past the ~90-day sync cap, which is what makes F1's calibration and F2's BG/NBD genuinely sharp. Sequence at least F5 alongside or before this work if history is thin.
- **Alert fatigue (F3).** The cap/ranking is load-bearing; tune it against real notification volume, and prefer one narrated digest over many raw notices.
