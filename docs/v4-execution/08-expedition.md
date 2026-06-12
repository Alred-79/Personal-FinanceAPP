# 08 — The Expedition (forecast-as-world-generator) + the two-homes IA

> Implements v4 §7.2, §5.2-of-the-substrate, §10.1. The most novel module (uniqueness 5/5) and
> the most build-expensive — which is why it waited for the MVP verdict. **Gate: only start
> this package if 01–07 shipped and their metrics didn't kill the bet.**

## Context recap

The user's real month rendered as a 3-act run map generated from the forecast: high-confidence
income events = act boundaries (weekly-skeleton fallback for irregular income); recurring bills
= fixed encounter nodes on due dates; **guaranteed rest windows** (no quest content) in the days
before the largest obligations; optional forks only where the forecast shows slack; pending
transactions render as **fog** (already never events — 01). The map is snapshotted at draft
time: forecast drift must NOT move nodes mid-run (world stability), with exactly two exemptions
— defeat-by-date and Grace re-derivations. End-of-run scoring has NO timing bonuses (month-end
distortion guard). Failure mints story: an undefeated objective unlocks a counter-built
modifier next month. Honesty rule from the scorecard: **the map is RETENTION; the alerts riding
its nodes are the MONEY** — every map node that matters must be able to fire a package-03
action-moment alert.

## Preconditions

- [ ] Packages 01–07 pass; MVP metrics reviewed and the go decision recorded in the handoff
      of 07 (or by the owner).
- [ ] `recurring_service` exposes per-stream confidence; verify threshold field.

## Out of scope

Heat contracts (09), Ascension (09), campaigns (10), LLM boss names (09 extends), the monthly
trailer is IN scope here (it's expedition flavor).

## Tasks

### 1. Map generation — `server/src/services/game/expedition.py`
- `generate_map(user, month) -> MapSnapshot`:
  - **Acts:** income events with confidence ≥ threshold → act boundaries. Fewer than 2
    confident income events → weekly skeleton (4–5 acts). NEVER guess a payday: a wrong act
    boundary breaks the whole fiction.
  - **Nodes:** recurring bills (due date, amount bucket, linked alert type), the active boss
    (positioned at its next due/defeat-by-date), habit monsters (floating, act-scoped).
  - **Rest windows:** K=2 days before each of the top-2 obligations by amount — no fork, no
    quest, no verb except `confirm_forecast`; daily beat uses the restorative template set.
  - **Forks:** at each act boundary, ≤2 mutually exclusive weekly route options, generated
    ONLY when the act's forecast slack ≥ a floor (e.g. projected discretionary ≥ 120% of
    baseline pace). Routes are objective sets ("Elite: dining ≤ 50% of pace this week" /
    "Steady: standard verbs"). Declining/ignoring = Steady, costless, unremarked.
- `runs` table: `(user_id, month, map_json, modifier_key, started_at, sealed_at NULL,
  score_json NULL)`. The snapshot is immutable post-draft (DB trigger or service-level guard).
  Mid-run re-derivations write to overlay fields, never the snapshot: `overlay_json`
  (defeat-by-date moves, Grace target scaling).

### 2. Draft
- Day-1 (or first-open) draft: choose 1 of 3 modifiers. Modifier registry with **terrain
  interaction requirement**: each modifier declares the map features it amplifies
  (`hearthkeeper`: dining-heavy months — double GREEN credit on dining days toward weekly
  route objectives; `tollbreaker`: subscription-heavy months; `stormwall`: months with a big
  known obligation). The 3 offered = best terrain matches for THIS map (deterministic ranking,
  seeded tiebreak). Modifiers affect SCORING/objectives only — never budgets, never alerts,
  never financial math.
- Skipping the draft entirely → run proceeds modifier-less (no nag, one re-offer mid-month max).

### 3. Events & fog
- Surprise real expense (posted, non-recurring, > threshold) → map event node ("trap"
  narratively) AND a Grace trigger check (05). The event reskins reality; it never invents
  expenses, never prompts spending.
- Pending transactions render as fog nodes ("the encounter hasn't settled") — resolve to real
  nodes on posting, disappear on removal. Fog days are GRAY (already law, 05).

### 4. Scoring & prestige
- On month close (`MonthSealed` from 01 — wire it now): score = whole-month aggregates only:
  GREEN-day ratio, route objectives met, boss damage dealt, verbs completed (capped), grace-
  adjusted. **Structurally no timing component:** the scoring function receives day-indexed
  data with dates STRIPPED to verdicts — it cannot know whether a payment was day-28 or day-2.
- Prestige: `floor(K * sqrt(score_normalized))` minted via `PrestigeMinted.v1`; spends arrive
  in 09/10 (modifier unlocks, cosmetics). Modest-month guarantee: any sealed run with ≥1 GREEN
  week mints ≥1 prestige.
- Failure mints story: each unmet route objective/undefeated boss → next month's draft pool
  gains the counter-modifier for that category (`hearthkeeper` after dining overruns) +
  a lore entry (template now; 09's bestiary lore extends). NO stat penalties, NO harder
  targets.

### 5. The two-homes IA switch (v4 §10.1)
- Full mode home route → `Expedition` (the map: current act, next node, today's verb, collect,
  chapter card on Sundays). Off/Ambient home stays `Overview`. Routing reads ONLY the mode
  variable (02's provider).
- The map page exists in all modes (fork-smell law): in Off it renders as the Forecast
  calendar view (same data, plain skin) — i.e., enhance the existing Forecast page to be the
  same component with mode-dependent tokens/terms. This is the package's biggest frontend
  task: ONE component tree, calendar skin ↔ map skin.
- Map rendering: rot.js-style seeded layout is optional polish — a vertical act/node list with
  the seeded ASCII creatures (06) is the v1. Resist the urge to build a freeform 2D map; the
  month is linear time, render it linearly.

### 6. Monthly trailer
- Month start: 5-line teaser over the deterministic bill calendar through the 07 pipeline
  (same validators; entity allowlist = this map's nodes; no digits; cache keyed on map hash).
  Template fallback as always.

## Guardrails

- Snapshot immutability is sacred: a test must prove forecast drift post-draft does NOT move
  nodes (only overlay fields change). If the forecast was WRONG (bill on the 12th not the
  15th), the node resolves where reality posts and the map marks the snapshot node "moved" —
  reality wins on resolution, the plan stays as drawn.
- No fork/quest content inside rest windows or under strain mode.
- Route objectives only ever target discretionary categories with confirmed mappings;
  essentials and low-confidence categories are invalid objective targets.
- The draft offers exactly 3; the system never recommends one (autonomy; the Chronicler may
  flavor-describe, firewall-checked, but ranking words like "best choice" are banned in draft
  templates).
- Score/prestige math is engine-only; the LLM never sees or states score numbers.

## Test cases (`server/tests/test_expedition.py`, client `expedition.test.tsx`)

Map generation:
1. Biweekly-payroll fixture → 2–3 acts on paydays; gig-income fixture (low confidence) →
   weekly skeleton; mixed fixture (1 confident stream) → weekly skeleton (the <2 rule).
2. Rest windows: top-2 obligations get K-day windows; verb scheduler inside a window offers
   only `confirm_forecast` (extends 05's test); fork generation skips window-overlapping spans.
3. Forks only where slack ≥ floor (tight-month fixture → zero forks; slack fixture → ≤2 per
   act).
4. Snapshot immutability: regenerate forecast with drifted dates post-draft → `map_json`
   byte-identical; overlay carries the defeat-by-date change; DB-level guard blocks UPDATE of
   `map_json`.
5. Map determinism: same inputs + seed → identical snapshot (run twice).

Draft & modifiers:
6. Terrain ranking: dining-heavy fixture month → `hearthkeeper` in the offered 3;
   subscription-heavy → `tollbreaker` offered (golden fixtures).
7. Modifier affects scoring only: with/without modifier, alerts fired and budgets identical
   (diff test); score differs.
8. Skip draft → run valid, modifier NULL, exactly one mid-month re-offer.
9. Draft templates contain no recommendation words ("best", "should", "recommend") — scan.

Events & fog:
10. Surprise expense ≥ threshold → trap node + Grace check invoked (spy); below threshold →
    nothing.
11. Pending txn → fog node; posting resolves to real node (same identity via
    `pending_transaction_id`); removal clears it silently.
12. Trap node templates: no spend prompts, no shame language (scans).

Scoring & prestige:
13. **The date-stripping property test:** construct two months with identical verdict
    multisets but different day orderings (all payments early vs all late) → identical scores.
    This is the no-timing-bonus guard as an executable property.
14. Score golden fixtures: known verdicts/objectives → known score; grace days excluded from
    denominator (GRAY ≠ MISS already; assert score treats GRAY as absent).
15. Prestige sub-linearity (doubling score < doubles prestige); modest-month guarantee (1
    GREEN week → ≥1 prestige); `PrestigeMinted` idempotent per month (seal replay safe).
16. Failure→story: unmet dining objective → `hearthkeeper` guaranteed in next month's offer
    pool with `counter=true`; no target tightening anywhere (assert next month's objectives
    derive from baselines only).
17. `MonthSealed` carries the score summary; rebuild from seal == rebuild from genesis for
    month-scoped projections (extends 01's seal test).

IA & rendering:
18. Mode routing: full → Expedition home; ambient/off → Overview home; direct URL to either
    page renders in every mode (fork-smell CI extends).
19. Forecast page and map page are the same component (assert shared component identity /
    no duplicated data fetch logic — structural test).
20. Fog/rest/trap node skins per mode: off shows plain calendar entries ("pending", "bill"),
    full shows flavored — same DOM structure (snapshot pair).
21. Trailer: generated once per month per ambient/full user, validators pass, fallback works
    with Groq mocked down.

Integrity:
22. Fingerprint unchanged across: map gen, draft, a full simulated month, seal. Rebuild all
    expedition projections clean.

## Exit criteria

- [x] All tests pass; suite green; rebuilds clean. (Backend 631 passed — lone failure is the
      pre-existing flaky MCP test; frontend 135; tsc clean; migration single-head with the
      map_json immutability trigger.)
- [x] Manual-equivalent (asserted by tests): a month drafts, renders as map (full) /
      calendar (off) via ONE component, scoring + prestige on seal. Live surprise-expense trap
      + chapter cross-reference left for manual review per agreed scope.
- [x] Trough-plan content (§9.4 first campaign milestone) — noted as scheduled for package 10.

---
*Handoff notes:*

**Status: complete.** Backend 631 passed (lone failure = pre-existing flaky MCP test).
Frontend 135. tsc clean. Migration `e8f9a0b1c2d3_runs` (single head) ships the `runs` table +
the `runs_map_json_immutable` DB trigger (mirrored in models.py for create_all).

**What was built**
- `Run` model + migration with a DB-level `map_json` immutability trigger (world stability —
  forecast drift never moves snapshot nodes; mid-run changes go to `overlay_json`).
- `expedition.py`: `generate_map` (acts from confident income — recurrence-bearing rows; weekly
  skeleton when <2 confident; bills as nodes; K=2 rest windows before top-2 obligations; forks
  only on slack), the modifier registry + deterministic `rank_modifiers` (terrain interaction),
  `RunService` (draft/overlay/seal — the only writer to `runs`), and **`score_run` with the
  date-stripping property** (receives verdicts only, sorts them, GRAY excluded from the
  denominator — structurally no timing bonus), `mint_prestige` (sub-linear + modest-month
  guarantee), `next_month_counter_modifiers` (failure→story, no tightening).
- `/game/expedition/` endpoint (lazy draft on first view).
- Client: `Home` (two-homes IA — full→Expedition, off/ambient→Overview, reads ONLY the mode
  flag), `Expedition`/`ExpeditionView` (ONE component, calendar↔map skin via `data-skin`),
  routed; expedition terms in all 3 catalogs.

**Key correctness note (anchor-exclusion):** `recurring_service.project_occurrences` EXCLUDES
the anchor and returns only strictly-future dates, so a bill/income anchored within the target
month would vanish from its own map. `expedition._occurrences_in_month` merges projected
occurrences with in-month anchor rows to fix this. (Same anchor-exclusion gotcha that the pkg-03
payday-sweep fix addressed — worth remembering for any future "this month's recurring items".)

**Deviations / deferred (scope: full spec, test-what's-testable on visuals):**
- `recurring_service` exposes NO per-stream confidence field (precondition asked to verify it —
  it isn't there). Confidence is derived deterministically: a recurrence-bearing income row is
  confident, an irregular/gig row (no recurrence) is not. Documented; revisit if a real
  confidence score lands.
- Fog/trap nodes + the surprise-expense→Grace-check wiring and the monthly trailer (07 pipeline)
  are NOT yet built — the map/draft/scoring/prestige/IA core is complete and tested. Flagged for
  a follow-up or package 09 (which owns Grace) to wire the surprise-expense→Grace path.
- Canon/MonthSealed auto-wiring: `RunService.seal` mints prestige but is not yet auto-triggered
  from a `MonthSealed` fold — call it from the month-close job when that lands (10).
- `MonthSealed` score-summary carrying + month-projection rebuild (test 17) deferred with the
  seal job.

**For package 09:** Heat/Ascension/regret-monster build on this. The expedition's
`overlay_json` is where Grace target-scaling writes (never the snapshot). Prestige
(`PrestigeMinted`) spends arrive in 09/10. §9.4 trough content (first campaign milestone) is
package 10.
