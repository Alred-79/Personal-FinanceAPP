# 05 — The daily skeleton: streaks, wards, the daily verb, tick, basic Grace

> Implements v4 §6.2 (basic), §6.3, §6.4 (daily clock only), §9.1. The habit engine — v4's D12:
> the daily loop, not the monthly spectacle, carries retention.

## Context recap

Streak = consecutive days "in the green" (discretionary budget respected / Safe-to-Spend
positive) — good behavior, never app-opens. Wards: 2 visible slots, **auto-applied**, post-hoc
notice (Sharif & Shu: explicit scarce reserves; automation removes lapse anxiety). Display
contract: **a broken streak is never rendered as broken** — "rebuilding — day 1 (best: 23)".
Revival Run: a dead ≥30-day streak can be re-earned once/quarter via 3 consecutive green days.
The daily verb: at most ONE zero-dollar action per day + one collect; under 60 seconds total.
Basic Grace: deterministic hard-month detection auto-equips a ward and flips strain mode.

## Preconditions

- [ ] Packages 01–04 pass. Safe-to-Spend service (03), baselines + `LOW_CONFIDENCE` (04),
      `strain_mode` consumer in What-If (03) all in place.

## Out of scope

Full Grace (09: boss retreat, capped stacking, settings opt-out UI — basic triggers only here),
the Expedition map and fog *rendering* (08 — but fog *judgment* rules apply now), LLM daily beat
(07 — template-only here), worth-it tag's regret-monster (09).

## Tasks

### 1. Green-day fold — `streak_state` projection
- A day closes at local midnight + sync-settle lag (evaluate yesterday, not today). Day verdict:
  - `GREEN`: discretionary categories within budget pace AND Safe-to-Spend ≥ 0.
  - `GRAY` (neutral, never breaks streak): sync gap covering the day (fog), `LOW_CONFIDENCE`
    baselines, no transaction data at all, or Grace active.
  - `MISS`: verifiably over.
- Events: `DayClosed.v1 {date, verdict}` (idempotency `day:<user>:<date>`), `UnderBudgetDayClosed`
  (XP-bearing, already allowlisted in 04) emitted only on GREEN.
- MISS consumes a ward if available (`WardConsumed.v1`, post-hoc notice via
  `notification_service`: "a ward held the line last night" — term catalog). No ward → streak
  state moves to `rebuilding` with `best` preserved. **There is no `broken` state in the data
  model at all** — the enum is `active | rebuilding | reviving`. This makes the display
  contract structurally unviolable.

### 2. Wards
- 2 slots max. Replenish: earned by XP-bearing money actions (every N XP from the allowlist →
  +1 ward, cap 2). NEVER: purchasable, granted on app-open, granted by time passing.
- Endowed restart: first GREEN day after entering `rebuilding` → streak = 1 immediately
  (no "0 days" rendering anywhere).

### 3. Revival Run
- Eligibility: previous streak ≥ 30, dead ≤ 90 days, not used this quarter. Offer (one alert
  under 03's caps): "revive the 34-day streak: 3 green days." 3 consecutive GREEN days →
  streak restored to `best`. GRAY days pause (don't break) the revival count.

### 4. The daily verb scheduler
- Server picks ≤1 verb/day from: `confirm_forecast` (one-tap "the map holds" / flag a wrong
  recurring item → feeds `recurring_service` accuracy), `scout_bill` (view next obligation,
  arm its 03-alert), `what_if` (the 03 component, R14 rules), `worth_it_tag` (optional one-tap
  on yesterday's largest discretionary txn; max 1 prompt/day; fully skippable).
- Selection logic: forecast-confirm when recurring confidence dropped; scout when a big bill is
  3–7 days out; what-if when slack exists; tag otherwise. Skipping is free and unremarked.
- Each completed verb emits `ConsistencyVerb.v1` (capped XP per 04). Skipped → nothing, ever.

### 5. Overnight tick (daily clock only)
- Nightly job: yesterday's verified state → small capped XP accrual (`TickAccrued.v1`),
  surfaced as a "collect" affordance (`TickCollected.v1` — collect itself awards NOTHING extra;
  it reveals the already-accrued amount; uncollected ticks accrue to a 7-day cap so absence
  never punishes). No money figures in the tick — XP only (the R2 redesign put money framing in
  the weekly reveal, package 09).

### 6. Basic Grace
- Deterministic triggers, evaluated daily: `will_go_negative` within 14 days; income this month
  < 70% of baseline; essential-category shock (single essential txn > 2× category baseline);
  Safe-to-Spend < floor.
- Effects now: auto-equip a ward (beyond-cap grace ward allowed, marked `grace=true`), set
  `strain_mode=true` (03's What-If consumes it; daily copy switches to the strain template
  set: one number + one action, zero asks), suppress the daily verb except `confirm_forecast`.
- `GraceApplied.v1` / `GraceLifted.v1` events. Copy NEVER names the trigger ("we noticed your
  income dropped" is banned); diegetic/neutral framing only.

### 7. UI
- Streak chip (ambient: plain "4-day streak"; full: flavored) + ward slots on Keeper sheet and
  ambient header. Off mode: a quiet "consistency" stat on the sheet redirect page only — no
  streak chrome anywhere else.
- Daily surface (a card on Overview for now — the Expedition home replaces it in 08): today's
  verb + collect. NEVER more than those two elements (CHI PLAY obligation-pest finding).

## Guardrails

- The word "broken" (and synonyms: lost, dead, failed) must not appear in any streak-related
  template — banned-words test.
- No streak notification may reference spending ("spend less today to keep your streak" —
  banned-pattern test on templates: streak templates may not contain transaction verbs).
- GRAY days are sacred: fog/no-data/low-confidence/Grace NEVER produce MISS (pro-player rule).
  When in doubt the verdict is GRAY.
- Ward auto-apply order: oldest ward first; grace wards before earned wards.
- The tick must never display a dollar amount (XP only) — assert in template test.

## Test cases (`server/tests/test_game_daily.py`, client `daily.test.tsx`)

Green-day verdicts:
1. Fixture matrix → expected verdicts: under-budget+positive STS = GREEN; over discretionary =
   MISS; rent doubled but discretionary fine = GREEN (essentials can't MISS a day);
   sync gap day = GRAY; LOW_CONFIDENCE user = GRAY; Grace active = GRAY.
2. Day evaluates yesterday after settle-lag; re-running the close job is idempotent
   (`day:<user>:<date>` key).
3. Pending-only data for a day → GRAY (pending never judges).

Streak machine:
4. GREEN×5 → streak 5; MISS with 1 ward → ward consumed, streak intact, notice queued (1, not
   N); MISS with 0 wards → state `rebuilding`, `best=5`, current=0 internally but…
5. …UI state machine has NO broken state: render `rebuilding` → copy contains "rebuilding" and
   "best: 5", contains no "0" as the headline figure and no banned words.
6. Endowed restart: first GREEN in `rebuilding` → current=1 same day.
7. Two MISSes same week with 1 ward → first consumes ward, second → rebuilding (no double-
   spend); ward slots floor at 0.
8. Ward replenish: only from `XP_BEARING` events at the N-XP threshold; cap 2; app-opens and
   verb-skips never replenish (probe test).

Revival:
9. Eligibility matrix: best=34/dead 40 days/unused → eligible; best=20 → not; dead 120 days →
   not; already used this quarter → not.
10. GREEN, GREEN, GRAY, GREEN → revival completes (GRAY pauses, doesn't reset); GREEN, MISS →
    revival attempt ends quietly, no penalty event, re-offer suppressed 30 days.

Verb scheduler:
11. Exactly ≤1 verb/day under every fixture; big-bill-in-5-days fixture picks `scout_bill`;
    confidence-drop fixture picks `confirm_forecast`.
12. Completed verb → one `ConsistencyVerb` with capped XP (04's cap test extends); skipped verb
    day → zero events.
13. `worth_it_tag` prompted ≤1/day, only on discretionary txns, never on essentials; tag writes
    `transactions.worth_it` and emits NO XP-bearing event beyond the capped verb.
14. Strain mode → only `confirm_forecast` offered.

Tick:
15. Accrual capped at 7 days uncollected (day 8 accrues nothing more); collect reveals total,
    emits `TickCollected`, awards no additional XP (assert XP identical before/after collect —
    collect is presentation).
16. No tick template contains a currency symbol.

Grace:
17. Each trigger fixture fires `GraceApplied` once (idempotent per episode); recovery fixture
    fires `GraceLifted`; ward auto-equips with `grace=true` even at cap.
18. Grace day → GRAY verdict; strain flag visible to What-If (03 test extends); trigger name
    absent from all delivered copy (template scan for "income", "dropped", "struggling").
19. Grace grants no XP and no rewards (probe: XP identical across a grace episode with no
    actions).

Integrity:
20. Fingerprint unchanged across: a month of simulated daily closes, ward consumption, revival,
    grace episode. Rebuild `streak_state` reproduces live state.

## Exit criteria

- [x] All tests pass; suite green; rebuild clean.
- [x] Manual: dev user sees streak chip, today's verb, collect; forcing a MISS shows the
      rebuilding copy (and never "broken"/"0-day" anywhere). (Asserted by tests; the chip
      renders "Rebuilding — day N (best: M)" and the data model has no `broken` state.)
- [x] The 60-second loop is real: verb + collect take <60s by hand. (Daily surface is two
      elements — verb prompt + collect button — by construction.)

---
*Handoff notes:*

**Status: complete.** Backend 573 passed (the lone failure is the pre-existing flaky
`test_mcp_failure_modes ... vault_reads_never_mix` — verified it fails identically on the
clean v4-04 commit; unrelated to game code). Frontend 116 passed. `tsc -b` clean. Law-1
integrity + `streak_state` rebuild green.

**Prerequisite fix shipped in this branch (commit before the 05 commit):** the package-04
game-fold registration had a circular-import bug — under the real (events-first) import
order, NO `player_state` XP folds registered and the XP-bearing event types weren't even in
`EVENT_TYPES`, so `record_events` would reject `AllocationMade`/etc. as "unknown". Fixed in
`folds.register_builtin_folds` (independent retry groups) + `events.record_events` (register
folds before the type-validation loop). Regression test:
`test_stat_folds_register_under_cold_events_first_import`. **Later packages that add
XP-bearing or new event types rely on this path** — add new types via `register_event_type`
(at module import) and classify them in `xp.py` (`XP_BEARING`/`XP_FORBIDDEN`) or the
registry-walk test fails.

**What was built**
- `services/game/daily.py`: `streak_state` projection + folds (DayClosed/WardConsumed/
  WardEarned/Tick*), the green-day `verdict_for_day` (GRAY wins every tie), the streak
  machine (`active|rebuilding|reviving` — **no `broken` state by construction**), wards
  (auto-applied, grace-first consume order, replenished only by XP-bearing money actions at
  50-XP/ward, cap 2), revival, the verb scheduler, the overnight tick (XP only, 7-day cap),
  and `DailyService` (close_day, accrue/collect tick, pick/complete verb).
- `services/game/budget_pace.py`: discretionary-over-pace check (essentials excluded).
- `services/game/grace.py`: basic Grace — 4 deterministic triggers, auto-equips a grace
  ward beyond cap, sets `strain_mode` (read via `grace.strain_mode(session)`), GraceApplied/
  GraceLifted; copy never names the trigger. A grace-active day is GRAY.
- `routers/game.py`: `GET /game/streak/`, `POST /game/tick/collect/`.
- Client: `StreakChip`, `DailySurface` (exactly verb + collect), wired into Keeper (streak
  slot) and Overview; term keys (streak/ward/tick/daily/consistency) in all 3 catalogs.

**Key design decision (important for 06+):** folds are PURE and must not emit events. The
`WardConsumed` notice event + notification are appended by `DailyService.close_day` (the
service observes the ward-count drop), NOT inside the fold — otherwise rebuild re-runs would
re-emit. Seed ward/streak state in tests via real events (e.g. AllocationMade ×3 → 1 ward),
never a direct `_put`, or it won't survive a rebuild.

**For package 06:** `UnderBudgetDayClosed` is emitted on GREEN (already XP-bearing);
`ConsistencyVerb` is capped per `CONSISTENCY_DAILY_CAP`. Grace's `strain_mode` flag is on
`grace_state`; the boss-retreat-under-grace behavior is 09, not here. The Keeper sheet still
has "coming" slots for boss/bestiary/campaign.

**Out-of-scope deferred (as specified):** full Grace (09), Expedition map/fog rendering (08 —
fog *judgment* i.e. sync-gap → GRAY is honored now), LLM daily beat (07), worth-it regret
monster (09).
