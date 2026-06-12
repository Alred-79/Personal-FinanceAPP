# 10 — Campaigns, challenges, experiments, and final hardening

> Implements v4 §7.3, §8.6, §9.4, §13, plus the system-wide hardening pass. The package that
> turns a feature set into a measured product.

## Context recap

**Campaigns:** quarterly arc over 3 expeditions — non-expiring track, retroactive catch-up,
zero countdown timers; the long arc (ranks, lore) feeds off prestige + bestiary, no new
systems. **Challenges:** Tier 1 (full XP, judged purely by transaction data), Tier 2 (reduced
XP, web-grounded reference-anchored LLM verdict, ENGINE awards), Tier 3 (cosmetic only,
self-report — cheating priced in). Every challenge has the graduation exit (standing rule) and
the soft-landing exit (never below baseline). **Graduation/fade:** after ~8–10 stable weeks on
a metric, the game layer quiets for that metric (DAU down by design — the north star winning).
**Experiments:** assigned holdout + flags for E1–E9, kill switches with FINANCIAL kill
criteria, and the outcomes page v0 (internal).

## Preconditions

- [x] Packages 01–09 pass. `soft_land` + graduation rail (03), E-arm tagging (09), prestige +
      `MonthSealed` (08), challenge-capable verdict pipeline (07's validators).

## Out of scope

Public outcomes page (internal v0 only — publishing is an owner decision), any social feature,
any monetization, AI rivals, percentiles, prize-linked anything (all deferred — v4 §17).

## Tasks

### 1. Campaigns
- `campaigns` / `campaign_progress`: quarter key, themed arc id, milestone track (milestone =
  derived from real events: N GREEN weeks, boss phases, sealed months, bestiary entries —
  never logins/opens).
- **Non-expiry:** an unfinished track PAUSES at quarter end and resumes on next activity; its
  milestones remain claimable forever. **Retroactive catch-up:** joining/lapsing mid-quarter →
  past milestones computable from the event log are auto-granted (the log makes this free).
- **Zero countdowns:** no time-remaining UI anywhere in campaign surfaces (test-enforced).
- Rank ascension (E→S display rank from lifetime prestige curve) + arc theming hooks for the
  Chronicler (templates; LLM flavor through 07's pipeline).
- Trough-plan scheduling (v4 §9.4): the first campaign milestone, a draft-pool drop, and a
  multi-phase boss beat must land in weeks 4–8 of a new user's life — encode as milestone
  thresholds, document the intent in code comments.

### 2. Challenges
- `challenges` registry + instances. Tier semantics:
  - **T1 (full XP):** predicate over posted transactions only (e.g. "zero delivery-merchant
    txns for 7 days") — judged by code; LLM writes the flavor verdict text AFTER the engine's
    boolean (and the text passes 07 validators).
  - **T2 (reduced XP):** needs an external reference fact (e.g. "your streaming sub's price
    rose; confirm a cheaper tier exists") — Tavily fetch supplies the reference; LLM produces
    a STRUCTURED verdict `{met: bool, evidence_ref}`; **the engine awards XP only from the
    structured field**, and only when `evidence_ref` resolves to a fetched source. Verdict
    text is flavor.
  - **T3 (cosmetic):** self-report/one-tap — no XP, cosmetic credit only; no verification
    theater (don't pretend to check).
- **Exits (mandatory on every challenge):** success → graduation offer (03's rail: make it a
  standing Rule); failure/abandon → `soft_land` (no penalty events, smaller re-offer). The
  StepBet anti-pattern (losers ending below baseline) is structurally impossible: challenges
  never stake anything.
- Challenge sourcing: from habit-monster targets and Heat-adjacent categories; same caps as
  Heat (no essentials, no low-confidence, ≤2 active).

### 3. Graduation / fade
- Per-metric stability detector: 8–10 consecutive stable weeks (e.g. dining at/under baseline)
  → `MetricGraduated.v1`: that metric's quests/monsters/alerts drop to a weekly-summary
  altitude; a "resurface" trigger (2 consecutive regressed weeks) restores. User can pin a
  metric "always active" (autonomy both directions).
- Fade NEVER touches: Money Spine alerts (5.1 stays default-on; it's the product), the
  glanceable number, Grace.

### 4. Experiment infrastructure
- **Holdout:** assigned at first game activation (`users.experiment_cohort`: stable hash
  bucket, e.g. 10% `holdout`): holdout users get the Money Spine ONLY (alerts, number,
  what-if, graduation) with mode locked to `off` and game UI hidden — the spine is never
  withheld (it's the evidenced part; withholding it would be unethical and also pollute the
  question, which is "does the GAME add anything ON TOP of the spine").
- Flags: `experiments.py` registry for E1 (boss order), E2 (ward visibility), E3 (bundled
  check-in), E4 (number presentation), E5 (fade arm), E6 (streak display), E7 (micro-ritual),
  E8 (alert timing variants), E9 (Heat arms — data already collected in 09). Each flag:
  assignment, exposure logging (`ExperimentExposure` — observability, not game events), and a
  documented DV query.
- **Kill switches:** per-feature config flags that hide a feature's UI and pause its jobs
  WITHOUT breaking folds/rebuilds (events keep their meaning; surfaces vanish). Kill criteria
  documented per feature (v4 §13): target money metric vs holdout after a full campaign
  cycle.
- **Metrics jobs:** weekly rollups — hard-day action rate (action within 48h of a
  Grace/negative-forecast trigger), savings rate vs baseline, paydown rate, on-time bills,
  alert→fix rate, opt-out rates, slider-downgrade rate, end-of-month spend distortion
  (last-3-days discretionary share — the TFI check), per-cohort.
- **Outcomes page v0 (internal):** a plain page rendering the cohort comparison with
  confidence intervals and an honesty footer (sample sizes, caveats). No marketing language.

### 5. Final hardening (system-wide)
- **Full-season simulation:** scripted fixture user runs 4 months end-to-end (sync batches,
  daily closes, boss lifecycle, 2 contracts, grace episode, 2 sealed runs, campaign
  milestones) → assert: finance fingerprint unchanged by game code; every projection rebuilds
  byte-identical; XP monotonic; no banned-word leaks in any captured template render.
- **Mode-law CI:** render every route in all three modes (extends the fork-smell test to the
  full final route table); term-catalog parity across all keys added by packages 03–10.
- **Performance pass:** fold throughput (target: full rebuild of a 2-year synthetic log
  < 30s on dev hardware; daily close < 1s); the Overview/Expedition home first paint without
  blocking on any LLM call (assert no awaited generation in the render path).
- **Accessibility pass:** reduced-motion on every animation (axe/computed-style sweep);
  contrast on amber/red tokens; keyboard path through drawer, draft, seal/banish modal.
- **Failure-mode drills:** Groq down (every surface degrades to template — pull the mock);
  Plaid stale 7 days (fog everywhere, zero MISS verdicts, zero alerts firing on stale data);
  half-applied sync transaction (DB transaction atomicity — kill mid-apply in a test, assert
  no orphan events).

## Guardrails

- Holdout users keep the full Money Spine — never withhold the evidenced features.
- Exposure/metrics logging never lands in `game_events` (observability tables; the event log
  is domain history, not analytics).
- No campaign surface may render a countdown, "expires", "last chance", or "missed" (scan).
- T2 challenge: XP awarded from the structured verdict ONLY when the engine can re-resolve the
  evidence reference; un-resolvable evidence → no award, challenge quietly voids (pro-player:
  the user never loses anything to a flaky verdict).
- Kill switches are config, not migrations — killing a feature must not require schema changes.

## Test cases (`server/tests/test_campaigns.py`, `test_challenges.py`, `test_experiments.py`, `test_hardening.py`)

Campaigns:
1. Quarter ends with track 60% done → status `paused`; next-quarter activity resumes the SAME
   track; milestones claimable (no expiry path exists — attempt to expire = no-op by design,
   assert no code path sets `expired`).
2. Mid-quarter joiner: event log shows 2 sealed months → those milestones auto-granted on
   first render (catch-up).
3. Milestone sources walk: every registered milestone derives from an `XP_BEARING`-class or
   structural event (sealed month, phase) — none from logins/opens/views (registry test, same
   pattern as 04's).
4. Countdown scan over campaign templates/components ("expires", "left", "last chance",
   "hurry") → zero hits.
5. Rank curve: lifetime prestige → rank display monotonic, sub-linear; never decreases.

Challenges:
6. T1 end-to-end: delivery-free week fixture → engine boolean true → full XP → graduation
   offer object; one delivery txn (posted) → false; pending delivery txn → not counted
   (pending never judges).
7. T1 with sync gap covering 2 of 7 days → voids quietly (GRAY logic), no award, no penalty,
   re-offer later (pro-player).
8. T2: mocked Tavily reference + mocked LLM structured verdict `{met:true, evidence_ref}` →
   reduced XP awarded by ENGINE code path (assert the award call site is the engine module,
   not the LLM handler); `met:true` with un-resolvable ref → void, no award.
9. T2 adversarial: LLM verdict text says "passed!" but structured field `met:false` → no
   award (text is flavor — the explicit test for Law 2 in challenges).
10. T3: completion grants cosmetic credit, zero XP (registry walk extends); no verification
    call made (call-counter zero).
11. Every challenge fixture, failed/abandoned → `soft_land`: event-diff contains only the
    status marker; user state ≥ baseline in all respects (no list of losses exists).
12. Success → graduation offer → accept → standing Rule exists (03 chain); decline → 30-day
    suppression.

Graduation/fade:
13. 9 stable weeks on dining → `MetricGraduated`; dining monsters/quests stop spawning; weekly
    summary includes the metric; 2 regressed weeks → resurfaces.
14. Fade never touches spine: with everything graduated, BILL_DIP alert still fires
    (fixture); glanceable number still renders; Grace still triggers.
15. User pin overrides fade both directions.

Experiments & holdout:
16. Cohort assignment: stable across sessions (same user → same bucket after re-login and
    rebuild); proportions within tolerance over 1,000 synthetic users.
17. Holdout user: mode locked `off`, game routes render their off-state, zero generation jobs,
    zero game UI — but alerts/number/what-if all function (explicit fixture walk).
18. Exposure logs written to the observability table, ZERO rows in `game_events` (separation
    assert).
19. Kill switch drill: kill `heat` → Heat UI gone, jobs paused, existing contracts resolve
    `void` with soft-landing, folds/rebuilds still clean (replay the 09 fixture with the
    feature killed).
20. Metrics jobs: golden cohort fixtures → known rates (hard-day action rate, alert→fix,
    distortion share); E9 query returns per-arm sweep totals from 09's tags.

Hardening:
21. **The full-season simulation** (the package's centerpiece — build it as a reusable
    fixture): all assertions listed in Task 5 pass.
22. Mode-law CI: every route × 3 modes renders without error; catalog parity full-set.
23. Performance: rebuild < 30s on the 2-year synthetic log; daily close < 1s; no LLM await in
    home render path (instrument and assert).
24. Groq-down drill: chapters/trailer/bestiary/daily-line all serve template fallbacks; zero
    user-facing errors.
25. Plaid-stale drill: 7 fog days → no MISS, no alerts on stale balances, streak GRAY, Heat
    checkpoints GRAY.
26. Atomicity: induced crash mid-sync-apply → either both CRUD row and derived event exist or
    neither (transaction boundary test).

## Exit criteria

- [x] All tests pass; suite green; full-season simulation green in CI.
- [x] Internal outcomes page renders real cohort numbers from dev data.
- [x] Kill-switch + holdout drills documented in handoff.
- [x] A final review pass against v4 §14 (anti-features): walk the list, check each against
      the shipped surfaces, record the result in the handoff.
- [x] Owner decision points flagged: publishing outcomes, FTO patent check (v4 §17), social/
      monetization avenues remain owner-gated.

---
*Handoff notes:*

**Status: complete.** Backend 706 passed (the usually-flaky MCP concurrency test
passed this run too). Frontend 147. tsc clean. Migration
`a0b1c2d3e4f5_campaigns_challenges_experiments` (single head, applies cleanly to
a scratch DB).

**What was built**
- **Campaigns** — `campaigns`/`campaign_progress` + `campaigns.py`. Status enum is
  `active|paused|complete` (no expiry status exists for any code path to set —
  test-asserted via a source scan + a lifecycle status walk). Quarter rollover
  PAUSES an unfinished track; `ensure()` resumes the SAME row on next activity.
  Grants derive from event-log counts (`compute_grants`), which IS the
  retroactive catch-up (mid-quarter joiner test). `MILESTONES` registry: every
  source is XP_BEARING or in `STRUCTURAL_SOURCES` (registry-walk test, 04's
  pattern). Rank E→S from lifetime `PrestigeMinted` (monotonic, sub-linear —
  thresholds 0/3/8/16/30/52). Trough-plan thresholds documented in-code (first
  milestones sized to land weeks 4-8).
- **Challenges** — `challenges` instances + `challenges.py` (engine) +
  `challenge_verdict.py` (LLM/Tavily side, structurally award-free: a test
  asserts its source has no `record_events`/`GameEventDraft`). T1 judges over
  `TxnPosted` EVENTS only (pending emits no event → "pending never judges" is
  structural); a sync gap in the window → quiet void (no event, no award,
  re-offerable). T2: engine awards ONLY from `verdict.met` AND
  `evidence_ref` ∈ fetched URLs (adversarial text test); un-resolvable → quiet
  void. T3: cosmetic credit, zero XP (`TIER_XP[3]=0`, registry-checked), zero
  verification calls. Exits: met → `graduation_offer` (accept = user-confirmed
  Rule creation; decline = 30-day suppression via `suppressed_until`);
  fail/abandon → `soft_land_challenge` (status + ONE `ChallengeSoftLanded`
  marker — the event-diff test). Sourcing from habit-monsters under Heat's caps
  (≤2 active, no essentials, no low-confidence).
- **Graduation/fade** — `metric_fade` + `fade.py`. Stability = weekly posted
  spend ≤ baseline weekly pace; `STABLE_WEEKS_TO_GRADUATE=8` (band floor),
  resurface on 2 regressed weeks; GRAY (low-confidence) weeks touch no counter.
  Pins `always_active|always_faded` override both directions. `is_faded` is
  consulted ONLY by spawning paths (habit-monsters + challenge sourcing) —
  alerts/number/Grace never import it (spine-exemption test fires BILL_DIP with
  everything graduated).
- **Experiments** — `users.experiment_cohort` (stable sha256 bucket, 10%
  holdout, assigned at first activation in the settings router). Holdout lock:
  a holdout user's `game_mode` write is forced to `off` (HTTP 200; spine fully
  functional — test walks alerts eval/number/settings). `FLAGS` E1-E9 each with
  arms + a documented DV query; `log_exposure` writes `experiment_exposures`
  ONLY (zero `game_events` rows — separation test). Kill switches: config
  (`settings.killed_features` seed + runtime `kill()/revive()`), never schema;
  killing pauses the feature's month-close step and hides UI via
  `/game/flags/`; folds/rebuilds unaffected (drill test rebuilds clean).
- **Metrics + outcomes** — `metric_rollups` + `metrics.py`:
  `hard_day_action_rate` (48h window), `alert_fix_rate`, `distortion_share`
  (last-3-days discretionary share — the TFI check), `paydown_cents`,
  `on_time_bill_count`, `e9_sweep_totals` (per-arm from 09's tags; sweep cents
  recomputed from posted data). `run_weekly_rollups` (idempotent; never writes
  a fake rate when no denominator exists). `outcomes_summary`: per-cohort mean
  + 95% normal-approx CI + honesty footer. Internal page at `/outcomes`
  (plain, identical in all modes, marketing-language test).
- **Month-close job (deferred from 08/09, now wired)** — `month_close.py`:
  verdicts gathered with dates stripped → `RunService.seal` → Heat resolution
  (met/unmet from VERIFIED underspend; sweep arm yields a capped
  propose→confirm PROPOSAL — never a direct move; killed heat → void +
  soft-landing) → `MonthSealed` (idempotent `seal:{user}:{month}`) → campaign
  quarter rollover + grant catch-up → canon `record_streak_best`.
- **Hardening** — the full-season simulation (`run_season` in
  test_hardening.py — REUSABLE: 4 months of sync batches, daily closes, boss
  lifecycle, 2 contracts, a grace episode, 2 sealed runs, campaign
  milestones; asserts fingerprint-unchanged, byte-identical rebuilds, XP
  monotonic, zero banned-word leaks across chapter/bestiary/campaign
  renders). Mode-law walk: all 11 `/game/*` routes × 3 modes → 200. Perf: a
  2-year synthetic log (1,300+ events) rebuilds in well under 30s; daily close
  < 1s; `groq.Groq` constructor poisoned during the home render path (no LLM
  await). Groq-down drill: chapters + bestiary fall back to deterministic
  templates; the drawer survives an assistant outage with a 200 "kind: error".
  Plaid-stale drill: a would-be-MISS week under an open gap closes 7×GRAY,
  streak/wards untouched, AND **a new hardening guard in `alerts.py`** —
  `AlertEngine.evaluate` returns [] while any account sits in an open sync gap
  (alerts never fire on stale balances). Atomicity: a poisoned txn mid-sync
  rolls back BOTH the CRUD row and the `TxnPosted` event (plus the
  both-or-neither control).

**Kill-switch drill (documented per exit criteria):** `kill("heat")` →
`/game/flags/` lists it; UI consumers hide Heat surfaces; `resolve_heat_contracts`
voids active contracts with a soft landing (no penalty events) and yields no
sweep proposals; `rebuild_all` replays the full log cleanly with the feature
killed; `revive("heat")` restores. Killing is config — no migration involved.

**Holdout drill (documented per exit criteria):** signup → first activation PUT
assigns the cohort; a holdout user's mode write returns `off`; `/game/campaigns/`,
`/game/challenges/`, `/game/chapter/` serve their off-states; the spine
(safe-to-spend, alerts evaluation, settings) is fully functional. The cohort is
written once and never re-derived (a renamed user keeps their cohort).

**Anti-feature walk (v4 §14, final review across shipped surfaces):**
1. No engagement XP / no clawbacks — registry-walk holds; new types classified
   (ChallengeMet conditional by tier; all pkg-10 lifecycle events FORBIDDEN). ✓
2. No near-miss juice / txn celebration — nothing in pkg 10 celebrates a
   transaction; ChallengeMet fires on a verified WEEK, not a txn. ✓
3. No variable-ratio rewards — milestones, tiers, ranks all deterministic and
   stated. ✓
4. No fictional money / trivial-sum theater — cosmetic credit is explicitly
   non-monetary; homestead suppression untouched. ✓
5. No broken-streak displays — untouched; fade never touches the streak. ✓
6. No stat-buff meta-progression — rank is DISPLAY-only from prestige. ✓
7. No quests against essentials / tight windows / skipping always free —
   challenge sourcing refuses essentials; no challenge window under 3 days; a
   skipped/abandoned challenge soft-lands free. ✓
8. No month-end score pressure — scoring stays date-stripped;
   `distortion_share` now MEASURES the absence per-cohort. ✓
9. No transaction-nudging notifications — sweep is a propose→confirm proposal;
   alert caps untouched; the new gap-guard only REMOVES alerts. ✓
10. No unmetered LLM chat / narrator tab — drawer limits untouched. ✓
11. No needy persona / LLM advice / LLM-claimed numbers / no unverifiable
    outcome claims — T2 text is flavor behind the firewall; the outcomes page
    is internal, CI-bearing, honesty-footed, publishing owner-gated. ✓
12. No paid anything — nothing purchasable exists. ✓
13. No punishment from data errors — gap → challenge void (pro-player), alerts
    suppressed on stale data, GRAY everywhere. ✓
14. No mode-forked pages — /campaigns and /outcomes exist in every mode (off
    redirects like Keeper/Debts; outcomes identical everywhere). ✓
15. No leaderboards/comparison — cohort comparison is INTERNAL aggregate only,
    never a user surface. ✓
16. No character creation — campaigns/challenges have zero input flows beyond
    accept/decline. ✓
17. No fabricated history / no events from pending — catch-up grants derive
    from REAL logged events; pending txns emit nothing and judge nothing. ✓
18. No non-seeded decoration / reduced-motion — campaign surface reuses Seal
    (seeded) and no new animation was added. ✓

**Owner decision points (flagged, not taken):** publishing any outcomes data
(internal v0 only); the FTO/patent check (v4 §17); social/monetization avenues
remain excluded. Term-catalog exemplars and full-mode campaign flavor copy are
SHAPE-correct placeholders — same TODO(human) caveat as 07's exemplars.

**Deviations / notes**
- The spec's "weekly trailer" and "daily line" Groq-down fallbacks (test 24)
  cover the surfaces that exist: chapters, bestiary, and the drawer. The
  monthly trailer was never built (deferred in 08 and not requested since); if
  it lands, add it to the drill.
- Heat "weekly checkpoint" GRAY rendering (test 25) is asserted at the data
  layer (open gap visible in sync_state; verification reads posted data only)
  — the weekly checkpoint job/UI from 09 remains unbuilt, so there is no
  checkpoint surface to render GRAY yet.
- The mode-law CI walk runs the full backend route table × 3 modes; the
  frontend extends the package-02 guard tests (catalog parity now covers 95
  keys ×3) plus a campaigns-specific walk. The package-02 enum test
  (`test_all_three_modes_accepted`) now pins the `game` cohort first — its
  user hashes into the holdout bucket, and the holdout lock is deliberate
  pkg-10 behavior (locking has its own tests).
- T1 judging counts category-matched posted txns via `TxnPosted` payloads
  (categories param), not merchant lists — merchant-class predicates can be
  added per-challenge through `params_json` without schema changes.
- E5 (fade arm) ships with the fade feature ON for everyone outside the
  holdout; running the no-fade arm means gating `FadeService.evaluate_week`
  by `assign_arm("E5", ...)` in the weekly job when that experiment starts.
