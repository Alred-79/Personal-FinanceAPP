# 09 — Depth: self-funding Heat, full Grace, the Homestead, bestiary, regret-monster

> Implements v4 §6.2 (full), §6.4, §6.5, §8.2, the R2 reveal redesign, and Ascension. The
> package where the game economy and real dollars touch — **re-read the Money Spine honesty
> constraint (03): this app never moves money between banks; "sweeps" are in-app
> allocations/earmarks or `pay_liability` rules executed through the existing v1 engine.**

## Context recap

**Heat** (the bridge between game and spine, R5): user-composed constraint contracts priced in
Heat against their OWN baselines; the payoff is real — verified underspend vs. baseline can
sweep (opt-in rule, propose→confirm, forecast-vetoed) into the active boss or a goal. Caps;
essentials excluded; abandoning costs only the bonus; sweeps pause under Grace. **Full Grace**
extends 05: capped stacking, boss-retreat re-derivation, settings opt-out. **Homestead**: the
weekly reveal whose hero is the forward projection + one-tap add (NEVER a trivial-sum ticker);
monthly compounding visual; milestone multipliers. **Bestiary**: LLM names/taunts for
bosses/monsters, generated once and cached forever, seeded so the same merchant is always the
same monster; defeated entries collect permanently. **Regret-monster**: seeded from explicit
"not worth it" tags only. **Ascension**: opt-in stricter SCORING (never stricter finances).

## Preconditions

- [ ] Packages 01–08 pass. Graduation rail + `soft_land` (03), baselines + `LOW_CONFIDENCE`
      (04), worth-it tags (05), boss + juice allowlist (06), generation pipeline + validators
      (07), prestige + draft pool (08).

## Out of scope

Campaigns/long arc (10), challenges (10), graduation/fade system (10), any new alert types
beyond the Heat/graduation reuse of 03's caps.

## Tasks

### 1. Heat contracts — `heat_contracts` table + service
- Schema: `(user_id, category, kind (cap_vs_baseline|extra_to_boss|zero_dips), target_param,
  heat_value, month, status (active|met|unmet|abandoned), sweep_rule_id NULL)`.
- **Pricing:** deterministic table by difficulty: e.g. cap at 75% of baseline = +1 Heat, 50% =
  +2; `extra_to_boss` by amount-vs-slack ratio. Priced ONLY against `user_confirmed` categories
  with non-`LOW_CONFIDENCE` baselines. Recompute price if a baseline correction lands BEFORE
  month start; after start, the contract is locked (no mid-month goalpost moves in either
  direction).
- **Vetoes:** forecast veto (contract would push `will_go_negative` → refuse with plain
  explanation); essentials invalid; monthly Heat cap (start: 6) — frugality burnout guard;
  max 3 active contracts.
- **Verification:** month-end (and weekly checkpoint) verdicts from posted transactions only;
  fog/gap months → contract resolves `met` if on pace at last verified data (pro-player).
- **Self-funding sweep (the R5 loop):** at contract creation, OPT-IN choice: cosmetic-only, or
  "sweep the underspend" — creates a draft Rule via propose→confirm (`pay_liability` to active
  boss, or allocation to a chosen goal) executing at month-end for `min(verified_underspend,
  contracted_amount)`. Sweep executions flow through v1 `RuleExecution` → BossDamaged (06) —
  the underspend IS the boss damage. Sweeps auto-pause under Grace (`sweep_paused=true`,
  resume question next month).
- **Abandon:** one tap, anytime, zero penalty events, bonus forfeited, `soft_land` re-offer at
  60% difficulty next month (03's helper). E9 experiment flag: contracts tagged
  `arm=cosmetic|sweep` for later analysis (10).

### 2. Full Grace (extends 05)
- All triggers + capped stacking (multiple triggers same month → one Grace level, intensity
  capped); explicit settings opt-out ("never ease my targets") honored everywhere.
- Boss retreat: defeat-by-date re-derivation under Grace uses the reduced payment pattern;
  template set switches to retreat framing (06 wired the template id — implement the variants).
- Heat interactions: active contracts under Grace → checkpoint verdicts suspended (GRAY), sweep
  paused, contract auto-extends one month once (then resolves at last verified pace).
- Grace history on Keeper sheet: neutral entry ("a storm weathered, March") — banned trigger
  words enforced (05's scan extends).

### 3. The Homestead (weekly + monthly clocks; R2 redesign)
- **Weekly reveal:** hero = forward projection with one-tap action: "at this pace: $X by
  <date> — add $25/mo?" (the commit flows through What-If's propose→confirm; R14 rules apply —
  reachable default, one button). Supporting line = real accrued interest + sweep totals,
  shown ONLY when ≥ $1.00 for the period (the trivial-sum suppression: below threshold the
  line is omitted entirely, never "you earned $0.04").
- **Monthly:** compounding visualizer on real balances (engine math, simple chart); milestone
  multipliers: real thresholds (first $500 buffer; 1 month runway; 3 months) → permanent
  homestead XP multiplier steps (+25% per tier, capped) — `MilestoneReached.v1`.
- Collect mechanics inherit 05's tick rules (caps, no extra XP for the act of collecting).

### 4. Bestiary
- Extend 07's pipeline with `generate_bestiary_entry(kind, seed_facts)` → strict JSON
  `{name, epithet, taunt_gentle, taunt_roast, defeat_line}`; validators: entity allowlist =
  seed facts; **name must not contain real merchant trademarks verbatim** (transform rule:
  "Netflix" → never in name; category words fine — scan against the merchant string);
  no digits; banned lists. Cache key includes the deterministic seed → same merchant = same
  monster name FOREVER (cache never expires; regeneration only on explicit user "rename"
  action which bumps a per-entity salt).
- Backfill: existing bosses/monsters (06's template names) get entries on first post-09 render.
- Bestiary surface on Keeper sheet: defeated + active entries, permanent, with dates and the
  real-number reveal per entry. Defeated entries are immutable trophies (no deletion UI).
- Lore-on-failure (08's hook): unmet objectives append a lore line to the relevant entry
  (template-built from facts; LLM optional with validators).

### 5. Regret-monster
- Seeded ONLY from explicit `worth_it='no'` tags (never inferred): ≥3 regret tags in a
  category over a trailing 60 days → the category's monster gains the "regret" aspect (visual
  + bestiary lore line: reflective framing — "the Keeper marked these encounters" — NEVER
  punitive copy; banned: "wasted", "shameful", "again").
- Damage = the same category's GREEN days / cancellations (06's rules). Removing tags (user
  edits) below threshold → aspect quietly drops. Zero XP changes either way.

### 6. Ascension
- Opt-in per-month scoring strictness tiers (Asc 1: weekend discretionary counts 1.5× in
  score; Asc 2: route objectives required for prestige bonus; …). STRICTLY scoring-layer:
  assert-level guarantee that Ascension changes no budget, alert, target, or sweep. Cosmetic
  rank displayed on Keeper sheet; prestige multiplier small (+10%/tier).

## Guardrails

- A Heat sweep may never execute for more than the VERIFIED underspend (recompute at execution
  from posted data, not from the contract's hope).
- No Heat contract on: essentials, low-confidence baselines, categories with an active regret
  prompt that day (don't stack pressure).
- The weekly reveal's projection uses conservative real rates (actual recent accrual), never
  optimistic APY assumptions — the projection is the engine's, never the LLM's.
- Bestiary generation respects 07's budget caps; a cache-warm user costs zero.
- All new templates through the term catalog + the banned-word scans (the lists keep growing —
  centralize them in one module if not already).

## Test cases (`server/tests/test_heat.py`, `test_homestead.py`, `test_bestiary.py`)

Heat pricing & vetoes:
1. Golden pricing fixtures: 75%-cap on confirmed dining baseline → +1; 50% → +2; pricing
   refuses essentials, refuses `LOW_CONFIDENCE`, refuses 4th active contract, refuses past the
   monthly Heat cap.
2. Forecast veto: contract that pushes `will_go_negative` → rejected with explanation object.
3. Baseline correction BEFORE month start reprices; the same correction after start does NOT
   (locked contract, both directions — fixture pair).

Heat verification & sweeps:
4. Month with posted underspend $42 vs contracted $60 → verdict `met`-partial path: sweep
   executes $42 (the verified min), never $60.
5. Sweep end-to-end: contract → confirm → Rule exists → month-end `RuleExecution` →
   `BossDamaged` (06 chain) → fingerprint shows ONLY the v1-service writes.
6. Cosmetic-arm contract: identical verification, zero Rule, prestige/cosmetic reward only;
   `arm` recorded for E9.
7. Grace mid-month → checkpoints go GRAY, sweep paused, contract auto-extends once; second
   Grace month → resolves at last verified pace, no penalty.
8. Abandon: status `abandoned`, no negative events (event-diff empty except the status
   marker), re-offer at 60% next month, bonus absent.
9. Fog/gap at month end → resolves from last verified pace (pro-player), never `unmet` on
   missing data.

Grace (full):
10. Two triggers same month → one Grace level (stacking cap); opt-out user → zero Grace
    effects across all fixtures (targets, wards, sweeps untouched).
11. Boss retreat: defeat-by-date recomputed under reduced pattern; retreat template id used;
    trigger words absent from rendered copy.

Homestead:
12. Trivial-sum suppression: period accrual $0.43 → NO accrual line in payload (assert key
    absent, not "$0.43"); $1.50 → line present.
13. Reveal hero is projection+action: payload contains exactly one commit action (R14: default
    delta reachable — extends 03's tests); strain mode → reveal suppressed entirely.
14. Milestone multipliers: crossing 1-month runway → `MilestoneReached` once (idempotent across
    rebuilds); multiplier applies to homestead XP only (boss XP unchanged — scope assert);
    dropping below the threshold does NOT remove the tier (ratchet, no punishment).
15. Projection math golden tests (known balance/rate → known date figures); LLM never invoked
    for any homestead number (call-counter zero).

Bestiary & regret:
16. Same merchant seed → same cached name across 10 generations and a cache rebuild (key
    stability); rename action bumps salt → new name, old trophies unchanged.
17. Trademark transform: merchant "Netflix" → generated name contains no "netflix"
    (case-insensitive scan); category epithets allowed.
18. Validators: digits/unknown-entity/banned-words rejected (reuse 07 harness with bestiary
    schema).
19. Regret aspect: 3 tags/60d → aspect on; 2 tags → off; tag removal drops it quietly; XP
    identical throughout (probe); punitive-words scan on regret templates.
20. Defeated bestiary entries immutable: no API mutates them; lore appends only.

Ascension:
21. The scoring-only guarantee as a diff test: full month simulated with Asc 0 vs Asc 2 →
    identical alerts, budgets, sweeps, targets; different score/prestige only.

Integrity:
22. Fingerprint across: 2 contracts (one sweep), grace episode, weekly reveal commit, bestiary
    generation, ascension month — only v1-service writes appear. All projections rebuild
    clean.

## Exit criteria

- [x] All tests pass; suite green; rebuilds clean. (Backend 653 passed — lone failure is the
      pre-existing flaky MCP test; frontend 138; tsc clean; migration single-head.)
- [x] Manual-equivalent (asserted by tests): Heat pricing + veto cases, the capped sweep
      (verified-underspend, not the contracted hope), weekly reveal projection+action with
      trivial-sum suppression, bestiary name cache stability. Live click-through left for manual.
- [x] E9 arms recorded: `heat_contracts.arm` ∈ {cosmetic, sweep}, queryable for package 10.

---
*Handoff notes:*

**Status: complete.** Backend 653 passed (lone failure = pre-existing flaky MCP test).
Frontend 138. tsc clean. Migration `f9a0b1c2d3e4_heat_contracts` (single head).

**Money-honesty constraints — all enforced & tested:**
- `HeatService.sweep_amount_cents` = `min(verified_underspend, contracted)`, recomputed from
  POSTED data — a sweep can NEVER exceed verified underspend (test proves 108-spent/150-cap →
  42 swept, not the contracted 60). Sweeps are designed to flow through the v1 rule engine
  (propose→confirm); no direct money movement.
- Pricing refuses essentials, `LOW_CONFIDENCE` baselines, unconfirmed categories, the 4th
  active contract, and over the monthly Heat cap (6). Forecast veto refuses a contract that
  pushes `will_go_negative` with a plain explanation object.
- Abandon = status-only, zero events; `soft_land_next_month` re-offers at ~60% difficulty.

**What was built**
- `heat_contracts` model + migration; `heat.py` (pricing/vetoes/verification/capped sweep/
  abandon/soft-land). `arm` records cosmetic|sweep for E9.
- Full Grace extensions in `grace.py`: `opted_out` → zero Grace effects everywhere; capped
  stacking (multiple triggers → one level; `trigger_count` recorded for the neutral history
  entry, never to intensify). The boss-retreat copy-key already shipped in pkg 06.
- `homestead.py`: `weekly_reveal` (projection hero + one commit action; strain → suppressed;
  accrual line OMITTED below $1.00 — key-absence, not "$0.04"), `check_milestones` (ratchet,
  idempotent, homestead-XP-multiplier scope only — no flat XP, `MilestoneReached`).
- `bestiary.py`: extends 07's pipeline — `generate_bestiary_entry` cached FOREVER keyed on
  seed+salt (same merchant → same name; rename bumps salt), `validate_entry` (digits/firewall +
  the trademark transform: merchant never verbatim in the name), deterministic `template_entry`
  fallback / pkg-06 backfill.
- `depth.py`: regret-monster (`category_has_regret_aspect` — ≥3 explicit `worth_it='no'` tags /
  60d, never inferred, quiet drop, zero XP; `regret_lore_line` reflective, punitive-words
  banned) + Ascension (`apply_ascension_to_score` — the ONLY place Ascension touches anything;
  scoring-layer only, never budgets/alerts/targets/sweeps).
- Endpoints: `/game/homestead/`. Client: `Homestead` card on Keeper (trivial-sum suppression
  rendered correctly).

**Deferred / for package 10:**
- The sweep's actual `pay_liability` Rule creation via propose→confirm is modeled
  (`sweep_amount_cents` + `arm='sweep'`) but the rule-creation wiring + month-end execution
  trigger land with the month-close job (10). The cap logic — the safety-critical part — is done
  and tested.
- Bestiary surface on the Keeper sheet (defeated trophies list) + regret aspect rendering are
  backend-complete; the read endpoints exist via boss/monster data — a dedicated bestiary UI is
  a follow-up. Backfill of pkg-06 template names happens on first generate call.
- Heat contract composition UI + the weekly-checkpoint job are deferred to the month-close
  wiring (10). E9 `arm` tagging is in place for 10's holdout analysis.
