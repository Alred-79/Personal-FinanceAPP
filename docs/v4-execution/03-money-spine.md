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

- [ ] All tests pass; full suite green.
- [ ] Manual: with dev data, the tab shows the number; an induced BILL_DIP fixture produces one
      alert with a working one-tap fix.
- [ ] Handoff documents the v1 service signatures used and any deviation.

---
*Handoff notes:*
