# 04 — Stat engine, XP hygiene, and the Keeper sheet

> Implements v4 §6.1. The shared substrate every later module reads.

## Context recap

Stats are **ratios against the user's own 3-month baselines**, never absolutes — a user saving
$50/mo from a tight income must be able to out-level one coasting on $2,000/mo (anti-wealth-
ranking, anti-shame, and the only fair Heat input later). XP attaches ONLY to verified financial
actions (OSC evidence: points attached to anything maximize that thing). The character sheet is
an **output** surface (R3: no character creation input flow exists anywhere in this app).

## Preconditions

- [ ] Packages 01–03 pass. Essential-category flagging exists (01). Term catalogs exist (02).

## Out of scope

Streak display (05), boss stats (06), Heat pricing (09 — but baselines built here are its
input), level-up *celebrations* beyond a toast (06 owns juice), any avatar art generation.

## Tasks

### 1. Baselines — `server/src/services/game/baselines.py`
- `category_baseline(user, category, as_of) -> cents/month`: trailing 3 calendar months of
  posted, user-confirmed-category transactions. Excludes: pending, transfers between own
  accounts, refund-matched pairs.
- `income_baseline`, `savings_rate_baseline` similarly.
- Baselines recompute on `TxnCorrected`/`TxnReversed` (subscribe a fold) — corrections adjust
  baselines silently; they never retro-judge past awards (the clamp rule lives upstream).
- New-user rule: <6 weeks of data → baselines are `LOW_CONFIDENCE`; consumers must check the
  flag (Heat will refuse to price against low-confidence baselines; stats render with a
  "calibrating" state).

### 2. Stats projection — `player_state`
- **Vitality** = runway: liquid balances ÷ trailing-3-mo essential+discretionary monthly spend,
  expressed in months, displayed bucketed (not a precise dollar figure — it's a stat, the real
  numbers live on finance pages).
- **Mana** = savings rate vs. own baseline (ratio, so improvement scores, not wealth).
- **Armor** = on-time-bill ratio × discretionary-budget adherence, trailing 30 days.
  Essential categories NEVER reduce Armor (a medical bill is not a defense failure).
- **Might** = net-worth delta + debt principal paid, vs. own baseline.
- **Level/XP**: XP sources allowlist `XP_BEARING = {PaymentPosted-derived events (06),
  AllocationMade, RuleExecuted, BillPaidOnTime, UnderBudgetDayClosed, WhatIfCommitted,
  AlertFixApplied (non-checklist kinds), ConsistencyVerb (capped, 05)}`. Level curve: sub-linear
  (`level = floor(sqrt(xp / K))` family) — choose K so a typical engaged month ≈ 1–2 levels
  early, slowing later. Document K in code.
- `ConsistencyVerb` daily cap: total consistency XP per day ≤ 10% of the median money-action XP
  value — the one argued exception to XP hygiene, capped so it can never compete (v4 §9.1).

### 3. Keeper sheet (client)
- New route/page `Keeper` visible in Ambient (plain wording: "Profile & Progress") and Full
  ("The Keeper"); **hidden entirely in Off** — but the route must still render (empty-state
  redirect to Settings) so the no-mode-only-pages CI rule holds: the page exists in all modes;
  its *presence in nav* is the flag.
- Output-card layout: the four stats with plain-term reveals (`<Term/>`), level/XP bar, the
  intensity selector (reused from 02), placeholder slots for streak (05), boss (06), bestiary
  (09), campaign (10) — render "coming" states, don't build them.
- Ambient header pip: tiny level indicator in the app header for ambient+full; nothing in off.

### 4. Toasts
- Level-up and stat-milestone events → existing `useToast`, copy via term catalog. No confetti,
  no sound, no animation beyond the existing stamp-in (juice arrives in 06, payoff-events-only).

## Guardrails

- **The registry walk test is the law's enforcement** (test 1) — any future event type granting
  XP must be added to `XP_BEARING` deliberately, and that test forces review.
- No stat may render a raw dollar amount on the sheet (bucketed/ratio displays only; the tap-
  reveal shows the real number — that's the transparency mechanism, not the stat itself).
- Stats never use red (boss-only color). Low stats use neutral phrasing ("rebuilding",
  "calibrating"), never shame terms — banned-words test on sheet templates ("failed", "behind",
  "worse", "only").
- No engagement XP: opening the sheet, checking stats, switching modes award nothing.

## Test cases (`server/tests/test_game_stats.py`, client `keeper-sheet.test.tsx`)

XP hygiene (the most important tests in this package):
1. **Registry walk:** iterate ALL registered event types; assert each is explicitly in
   `XP_BEARING` or `XP_FORBIDDEN`; assert `XP_FORBIDDEN` contains every engagement-shaped type
   (mode change, sheet view, login, collect-without-accrual, alert delivered, checklist fix).
   New unclassified type → test fails (this is intended friction).
2. Consistency-verb XP capped: 10 verb events in one day → XP equals the daily cap, not 10×.
3. Checklist-kind `AlertFixApplied` awards 0 XP; allocation-kind awards >0.
4. XP correction clamp end-to-end: award from a payment, then `TxnReversed` → XP unchanged,
   boss/financial projections (when they exist) would re-derive — assert payload records true
   negative delta.

Baselines:
5. 3-month window math against a fixture ledger (known transactions → known cents/month);
   month boundaries respected (calendar months, not 90 days).
6. Pending and own-account transfers excluded; refund pair nets out.
7. `TxnCorrected` shifts the baseline; no XP/stat re-judgment of past days (assert stat history
   rows untouched).
8. <6 weeks data → `LOW_CONFIDENCE` flag set; stats render "calibrating" state (client test).

Stats:
9. Armor ignores essential-category overruns (fixture: rent doubled → Armor unchanged;
   dining doubled → Armor drops).
10. Mana/Might are ratio-based: low-income fixture with improving rate outscores high-income
    flat fixture (the anti-wealth-ranking property, as an explicit test).
11. Vitality buckets correctly at boundaries (0.9 → "<1 month" bucket, 1.1 → "1–2").
12. Level curve: monotonic, sub-linear (level(4K)−level(K) < 3× level(K) sanity property);
    level never decreases (follows from clamp, but assert directly).

Sheet & UI:
13. Sheet renders in all three modes (off = redirect/empty state, ambient = plain labels,
    full = game labels with reveals); catalog parity auto-covers new keys.
14. Header pip hidden in off; present ambient/full.
15. Banned-words scan over sheet/toast templates.
16. Viewing the sheet 50 times emits zero game events (engagement-XP probe).

Integrity & rebuild:
17. Fingerprint unchanged by stat folds; `rebuild player_state` reproduces live state on the
    200-event property fixture from package 01.

## Exit criteria

- [x] All tests pass; suite green; rebuild clean.
- [x] Manual: Keeper sheet shows sane stats for dev data in all modes.
- [x] `XP_BEARING`/`XP_FORBIDDEN` lists documented in the handoff for later packages.

---
*Handoff notes:*

**Status: complete. Full suite green** — backend 550 passed (the lone
intermittent failure, `test_mcp_failure_modes.py::...vault_reads_never_mix`, is a
pre-existing flaky MCP/threading test from commit `d755689`, unrelated to game
code; passes on retry). Frontend 111 passed. `tsc -b` clean. Law-1
integrity/fingerprint/rebuild tests pass.

**What was built**
- Baselines (`services/game/baselines.py`): category/income/savings-rate, trailing
  3 *calendar* months, excludes pending + own-account transfers + refund-matched
  pairs; recomputes on `TxnCorrected`/`TxnReversed`; `<6 weeks → LOW_CONFIDENCE`.
- Stats (`services/game/stats.py`): Vitality (bucketed runway), Mana (savings-rate
  ratio vs own baseline), Armor (on-time × discretionary adherence, essentials
  never reduce it), Might (net-worth delta + principal paid, ratio). All
  ratio/bucket — no raw dollars on the card.
- XP hygiene (`services/game/xp.py`): the registry-walk law + level curve.
- Read surface (`routers/game.py`): `GET /game/keeper/` — pure output, no writes.
- Client: `pages/Keeper/Keeper.tsx`, header `LevelPip`, term keys in all 3 catalogs.

**Deviations (important for the next agent):** the original executing agent stopped
mid-package — work was uncommitted and NOT actually passing. A second agent finished
04. Fixes applied to make it green:
1. `Sidebar.tsx` rendered ALL nav items, leaking the gameOnly "Keeper" entry into
   **off** mode (broke the package-02 off-mode pixel-identity snapshot). Fixed by
   filtering `gameOnly` via `useFlags().gameLayer` — same pattern Header already used.
2. `Keeper.tsx` branched on bare `mode === "off"` (violates the package-02
   `mode === '<literal>'` grep guard). Switched to `useFlags().gameLayer`.
3. `Header.tsx` imported `LevelPip` which **did not exist** → `tsc -b` failed (prod
   build broken). Created `components/custom/LevelPip/LevelPip.tsx` (hidden in off,
   reads level from the keeper read surface, writes nothing).
4. The spec's client test `keeper-sheet.test.tsx` was missing — wrote it (cases
   13–16: per-mode render incl. off-redirect, pip visibility, banned-words scan,
   engagement-XP probe). 8 tests.
   **NOTE for later client tests:** the gameMode provider boots in `off` then
   resolves the persisted mode async, so a page that redirects synchronously in off
   races the boot. The test uses an `AfterModeResolves` gate to mount the route only
   once the provider settles — reuse this pattern for ambient/full page tests.

**`XP_BEARING`** (base XP/occurrence): `AllocationMade=20`, `RuleExecuted=15`,
`BillPaidOnTime=25`, `UnderBudgetDayClosed=10`, `WhatIfCommitted=20`,
`AlertFixApplied=15` (0 for `fix_kind=="checklist"`), `PaymentPosted=20` (handler
lands in 06), `ConsistencyVerb=5` (capped). To add a new XP source you MUST add it
here or the registry-walk test fails (intended friction).
**`XP_FORBIDDEN`:** `BackfillSnapshot`, `SyncGapOpened/Closed`, `TxnPosted`,
`TxnCorrected`, `TxnReversed`, `MonthSealed`, `XpAwarded`, `AlertFired`,
`ModeChanged`, `SheetViewed`, `LoggedIn`, `Collected`, `AlertDelivered`.
**Level curve:** `level = floor(sqrt(xp / K))`, `LEVEL_K = 120`.
**Consistency daily cap:** `CONSISTENCY_DAILY_CAP = max(int(median_money_xp*0.10),1)`
(currently 2) — package 05's `ConsistencyVerb` accrual must respect this.

**For package 05:** baselines + `LOW_CONFIDENCE` are in `services/game/baselines.py`;
`UnderBudgetDayClosed` and `ConsistencyVerb` are already in `XP_BEARING` (05 emits
them); the Keeper sheet has placeholder "coming" slots for streak/boss/bestiary/
campaign — 05 fills the streak slot.
