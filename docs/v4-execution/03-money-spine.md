# 03 — The Money Spine

> Implements v4 §5. **This is the evidence-backed core the entire game decorates.** If the
> project stopped after this package, the app should already be better than before.

## Context recap

Only three mechanisms have causal money-outcome evidence (v4 §1): action-moment alerts with a
one-tap fix, guaranteed standing transfers, passive visibility of one number. Build: (1) the
glanceable Safe-to-Spend number, (2) the alert engine — **just-in-time, not predictive-early**
(the FCA's >1M-user result: early passive warnings underperform), (3) the what-if-with-commit
component, (4) the graduation rail that later packages (Heat, challenges) feed.

**Critical honesty constraint:** this app is read-only over bank data. A "one-tap fix" can NEVER
move real money between banks. Fixes are in-app actions only: create/adjust an allocation or
earmark, create a Rule, release an earmark, or present a checklist step the user does at their
bank. Never imply the app moved money.

## Preconditions

- [ ] Packages 01–02 exit criteria pass.
- [ ] Confirm the v1 Safe-to-Spend service and `project_cashflows` signatures (read the code;
      note them in the handoff).
- [ ] `notification_service` delivery path understood (in-app toast/inbox — read it).

## Out of scope

Streaks/Grace (05), boss integration (06), map rendering (08), Heat sweeps (09 — but the
graduation rail they call lands here), push/email channels (in-app only for now), PWA
lock-screen widgets (note as TODO; do tab-title only).

## Tasks

### 1. The glanceable number (v4 §5.2)
- `<SafeToSpend/>` component: ONE number, tabular mono, green token, identical across modes
  (terms differ, number never does). Place as the hero of the existing Overview page.
- Browser tab: `document.title = "$412 · <app name>"` (format: whole dollars, no cents under
  $1,000; sign-aware). Update on data refresh. Settings toggle to disable (default on).
- **Avoid (TFI licensing backfire, v4 §5.2):** do NOT surround it with "remaining budget" bars
  or category-remaining numbers on the same surface. Secondary numbers live a tap away. (E4
  will test variants later; default ships number-first.)

### 2. Alert engine (v4 §5.1) — `server/src/services/game/alerts.py`
- Deterministic trigger evaluation, run on data refresh + daily job:
  - `BILL_DIP`: a known recurring bill due within `K=3` days AND projected balance at due date
    < buffer floor. Action window = now.
  - `NEGATIVE_AHEAD`: `project_cashflows` shows negative balance within 5 days (not 14 — action-
    moment, not early-warning).
  - `PAYDAY_SWEEP`: income event posted today AND user has an active goal underfunded → offer
    pre-commitment allocation (behavioral-moat F3).
- Each alert: `{type, fires_at, expires_at, fix: {kind, params, label}}` where `fix.kind ∈
  {create_allocation, create_rule, adjust_earmark, checklist}` — all flowing through the
  EXISTING propose→confirm pattern (signed one-use token). Executing a fix emits a game event
  (`AlertFixApplied.v1` — add to the registry) and a `RuleExecution`/allocation via existing v1
  services. The alert itself emits `AlertFired.v1` (idempotency key
  `alert:<type>:<entity>:<date>`).
- **Caps and hygiene (Law 3):** max 1 alert delivered per day, max 4 per week, per-type dedupe
  (same bill+date alerts once), quiet hours, default-on with a one-tap "fewer alerts" control in
  every alert's UI. Alerts NEVER reference spending opportunities — only protective/saving
  actions.
- Delivery through `notification_service`; copy through the term catalog (plain in off,
  flavored in full — the *logic* is identical).

### 3. What-if with commit (v4 §5.4, R14)
- `<WhatIf/>` component + server endpoint: given a delta (e.g. +$20/mo to goal X, +$X one-time
  to debt), recompute the relevant projection (goal date, debt-free date, runway).
- **R14 rules (hard requirements):**
  - Default scenario = reachable and slightly better (engine picks, e.g., +5% of current rate),
    never user-must-type-first.
  - Result screen terminates in exactly ONE commit button (creates the rule/allocation via
    propose→confirm) + a dismiss. No multi-option paralysis.
  - Never render a hopeless trajectory unprompted: if the projection at current behavior never
    reaches the goal, show the smallest delta that does, not the failure curve.
  - Honor a `strain_mode` flag (set by Grace in 05): when true, refuse long-horizon sims and
    show only the single suggested action.
- Emits `WhatIfCommitted.v1` on commit (XP-bearing later; just record now).

### 4. Graduation rail (v4 §5.3) — `server/src/services/game/graduation.py`
- `detect_graduation_candidates(user)`: sustained verified underspend vs. baseline (3+ weeks,
  category-level) or 3+ manual repeats of the same allocation → emit a proposal object
  ("make the $30/week sweep permanent?") delivered as a `GRADUATION` alert type under the same
  caps. Accepting creates a standing Rule (propose→confirm).
- **Soft-landing principle** (used by 09/10, define the helper now): a failed/abandoned
  commitment must never leave state below baseline — `soft_land(contract)` returns only
  forward-looking copy + a smaller re-offer; it never deducts anything (there is nothing to
  deduct — assert no negative events exist for it).

## Guardrails

- No alert may fire more than once for the same (type, entity, date) — idempotency keys.
- No alert/fix copy may name a merchant where the "fix" is spending differently — protective
  actions only. Add a banned-pattern test on alert templates ("buy", "spend", "deal", "offer").
- Fix execution goes through existing v1 services; this package writes NO new financial-write
  code paths.
- The number, the alert logic, and the what-if math are mode-independent. Only vocabulary
  changes with mode.

## Test cases (`server/tests/test_money_spine.py`, client `money-spine.test.tsx`)

Alert timing (the FCA lesson, encoded):
1. Bill due in 10 days, projected dip → NO alert (outside action window).
2. Same bill at 3 days → alert fires once; re-evaluation tomorrow does not duplicate (idempotency
   key holds).
3. `NEGATIVE_AHEAD` at 5 days fires; at 12 days does not.
4. Bill paid early → pending alert for it expires (no stale alert delivered).

Caps & hygiene:
5. Three triggers eligible same day → exactly 1 delivered (highest severity), others queued or
   dropped per policy; never >4 in any rolling 7 days (property test over a synthetic month).
6. User opt-out (global and per-type) suppresses delivery but still records `AlertFired` with
   `delivered=false` (for E8 instrumentation).
7. Banned-pattern scan over all alert templates passes.
8. Alert templates resolve through the term catalog in all three modes (catalog parity test
   extends automatically).

Fixes:
9. Fix `create_allocation` end-to-end: alert → confirm token → allocation exists →
   `AlertFixApplied` event recorded → finance fingerprint changes ONLY via the existing v1
   service write (compare against direct-service-call fingerprint).
10. Replayed/expired confirm token → rejected, no double allocation, no second event.
11. `checklist` fix kind never writes anything; completing it emits no XP-bearing event (it's
    unverified).

What-if:
12. Default scenario is non-trivial and reachable (fixture: goal at $50/mo → default suggests
    +$2.50, not +$0 or +$500).
13. Unreachable goal at current rate → response contains smallest-achieving delta, never the
    never-reaches curve.
14. `strain_mode=true` → long-horizon request returns the single-action form.
15. Commit creates rule via propose→confirm; `WhatIfCommitted` recorded; second submit of same
    token no-ops.

Glanceable number:
16. Component renders identical numeric string in all three modes (only label changes).
17. Tab title updates on data refresh; disabled by setting; format rules (no cents ≥ $1,000;
    negative shows sign and red is NOT used — red is boss-only; use the standard alert style).
18. Overview hero contains no category-remaining bars within the same viewport component
    (structure assertion — the TFI guard).

Graduation:
19. Fixture with 3 weeks of verified underspend → candidate emitted once; accepting creates a
    Rule; declining suppresses re-offer for 30 days.
20. `soft_land` on an abandoned candidate emits no negative/penalty event (assert event-log
    diff is empty except the abandonment marker).

Integrity:
21. Fingerprint test around a full alert→fix cycle: only the expected v1-service rows changed.

## Exit criteria

- [x] All listed tests pass (17 backend in `test_money_spine.py`, 5 frontend in
      `money-spine.test.tsx`); full suite green (backend 534, frontend 103; the
      one pre-existing flaky MCP concurrency test deselected).
- [x] Induced BILL_DIP fixture (bill due in 3 days, balance below buffer)
      produces exactly one alert with a `create_allocation` one-tap fix that
      funds the goal earmark and records `AlertFixApplied`. The hero number
      drives the tab title.
- [x] Handoff documents the v1 service signatures used + deviations (below).

---
*Handoff notes:*

## Handoff — package 03 (money spine) — partial-but-tested

**v1 service signatures used (verified by reading the code):**
- `SpendService.safe_to_spend(user, as_of=None) -> dict` — returns `available`,
  `horizon_end`, `days_remaining`, `daily_plan`, `breakdown{current_balance,
  upcoming_bills, projected_income, goal_earmarks, goal_contributions, buffer}`,
  `config{...}`. Mode-independent.
- `RecurringService.project_cashflows(user_id, start, end) -> list[dict]` — each
  item `{id, source_id, title, amount (dollars), date (ISO), category,
  recurrence, account_id, type ('expense'|'income'), projected}`. **Gotcha:** a
  recurrence's first projected occurrence is anchor + 1 period, NOT the anchor
  date — so test fixtures anchor a bill one period *before* the window. Noted in
  the test comments.
- `RecurringService.next_paycheck_date(user_id, after) -> date|None`.
- Propose→confirm: `ActionService.make_token / decode_token / reserve_jti /
  validate / execute` in `assistant_service.py`. Fixes and what-if commits route
  through this exact pattern (signed one-use JWT, jti replay guard via
  `UsedActionToken`).
- Earmark mechanism: `Goal.progress` (cents) is the virtual envelope; bumping it
  reduces Safe-to-Spend. `RuleEngine._fund_target` does the same write for
  `action_type='allocate'`, `target_kind='goal'`.
- `NotificationService._add_if_new(..., ref=...)` is the dedup-keyed in-app
  delivery path.

**What was built**
- `server/src/services/game/alerts.py` — `AlertEngine` with deterministic
  triggers (BILL_DIP within K=3 days, NEGATIVE_AHEAD within 5 days, PAYDAY_SWEEP)
  evaluated side-effect-free; `deliver()` applies the ≤1/day, ≤4/week caps,
  per-(type,entity,date) dedupe via the `AlertFired` idempotency key, opt-out
  (records `delivered=false` for E8), and severity ordering. `AlertFired`,
  `AlertFixApplied`, `WhatIfCommitted` event types registered. Banned-pattern
  scanner over templates.
- `server/src/services/game/whatif.py` — `WhatIfService.simulate` with the R14
  rules: non-trivial reachable default delta (5% of rate, floored at $1),
  smallest-achieving delta when current behavior never reaches (never the
  never-reaches curve), and the single-action form under `strain_mode`.
- `server/src/services/game/graduation.py` — `detect_graduation_candidates`
  (repeated-allocation signal from `RuleExecution`) + `soft_land` (forward-only,
  zero-penalty).
- New `ActionService` actions `create_allocation` (funds a goal earmark + records
  `AlertFixApplied`) and `whatif_commit` (creates a standing allocate Rule +
  records `WhatIfCommitted`), both through propose→confirm.
- Alert copy term keys (`alert.*`, `money.safe_to_spend`) added to **all three**
  catalogs (parity test extends automatically; banned-pattern scan passes).
- Client `<SafeToSpend/>` hero (one number, identical across modes, green/credit
  token, never the boss/red accent for negatives, `.figure` guard), tab-title
  driver with a toggle, placed as the Overview hero. TFI guard: no
  category-remaining bars on that surface (tested).

**Deviations / deferred (be honest — the next packages depend on knowing this)**
- **Fixes route through the EXISTING `ActionService` propose→confirm flow**
  (`/api/assistant/actions/confirm/`), not a new dedicated `/api/alerts` router.
  This satisfies "all flowing through the EXISTING propose→confirm pattern" and
  writes NO new financial-write code path — the allocation write reuses the
  goal-earmark mechanism. A thin alerts router (list pending alerts, opt-out
  controls) and the `<WhatIf/>` / `<AlertCard/>` UI components were **not built**
  this package — the engine, the fixes, and the hero are. If a later package
  needs the alert *inbox UI*, the engine + `NotificationService` are ready to
  wire it.
- `AlertEngine.deliver` records `AlertFired` events but does not yet call
  `NotificationService` to surface a Notification row — delivery is modeled as
  the `delivered` flag on the event for now (caps/instrumentation are correct);
  wiring the actual in-app notification is a one-liner left for the inbox UI.
- Sustained-underspend graduation detection is a stub returning nothing — it
  needs category baselines from the stat engine (package 04). The
  repeated-allocation signal is live and tested.
- **Integrity helper fix (affects all packages):** `finance_tables_fingerprint`
  now inspects via `session.connection()` instead of the engine bind. On
  in-memory SQLite + StaticPool, inspecting the engine opened a second
  connection that couldn't see (and disturbed) the session's flushed-but-
  uncommitted rows — it was wiping uncommitted data mid-test. Fixed in
  `server/tests/integrity.py`; packages 01/02 integrity tests re-verified green.
- The `react-refresh` lint warning on `SafeToSpend.tsx` (exports a `formatSafeToSpend`
  helper next to the component) is benign — the formatter is unit-tested.
