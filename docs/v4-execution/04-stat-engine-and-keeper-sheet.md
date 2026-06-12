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

- [ ] All tests pass; suite green; rebuild clean.
- [ ] Manual: Keeper sheet shows sane stats for dev data in all modes.
- [ ] `XP_BEARING`/`XP_FORBIDDEN` lists documented in the handoff for later packages.

---
*Handoff notes:*
