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

- [ ] Packages 01–09 pass. `soft_land` + graduation rail (03), E-arm tagging (09), prestige +
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

- [ ] All tests pass; suite green; full-season simulation green in CI.
- [ ] Internal outcomes page renders real cohort numbers from dev data.
- [ ] Kill-switch + holdout drills documented in handoff.
- [ ] A final review pass against v4 §14 (anti-features): walk the list, check each against
      the shipped surfaces, record the result in the handoff.
- [ ] Owner decision points flagged: publishing outcomes, FTO patent check (v4 §17), social/
      monetization avenues remain owner-gated.

---
*Handoff notes:*
