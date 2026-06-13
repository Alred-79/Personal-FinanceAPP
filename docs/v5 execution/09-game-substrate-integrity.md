# Step 09 — Game-substrate integrity

## Goal
Fix the game-logic bugs that are real *even single-user*, and give the dormant game jobs a
production entry point so the game features that have live endpoints aren't permanently empty.

## Why it matters (user impact)
Even with one user, these are visible breakages of the gamified layer the user opted into:
- **Bill alerts that fire once per database lifetime.** The alert idempotency key omits the
  recurrence/date, so after the first "NEGATIVE_AHEAD"/bill-dip alert ever, the same key suppresses
  every future one — the user stops getting the warnings the feature exists to give.
- **Silent projection drift.** A failed fold is swallowed while the watermark still advances, so
  XP/streak/homestead can quietly desync from the event log with **no failure/"behind" signal**
  anywhere (the watermark is the *progress* marker, not a health marker — the gap is that nothing
  records that a fold *failed*) and nothing triggers the rebuild the code comment promises. The user
  sees wrong numbers and no one knows.
- **Dead game features with live UI.** Month-close, fade, and graduation have **no production entry
  point** — only tests call them. (Weekly rollups are the exception: `weekly_reveal` *is* reachable
  via the game router, `routers/game.py:267,277` — so don't claim "weekly" is unreachable.) So
  months never seal, `/game/outcomes/` is always empty, expeditions are drafted but never scored.
  The user clicks into features that can never produce a result.
- **Heat sweep proposals wildly wrong** for `extra_to_boss`/`zero_dips` contracts, violating the
  "never sweep more than verified underspend" safety invariant — i.e. the game could propose moving
  more money than the user actually saved.

## Findings closed (with evidence)
- **Failed folds swallowed, watermark advances:** `game/folds.py:71-88` logs+skips a raising fold;
  `game/events.py:160-172` advances every projection's watermark regardless. The watermark is the
  *progress* marker (advancing it is required — see determinism contract below); the gap is the
  absence of a *failure/behind* marker, not the watermark itself.
- **Alert key omits recurrence/date:** `game/alerts.py:102-108` returns
  `f"alert:{self.type}:{self.entity}"`; recorded via `_record_fired` (`:335-350`) so the same key
  is reused forever.
- **Heat target_param treated as % for all kinds:** `game/heat.py:158-181`
  `cap_cents = base.monthly_cents * contract.target_param // 100` for every contract kind, but
  `extra_to_boss` means cents and `zero_dips` ignores it.
- **No production entry point (month-close/fade/graduation):** `close_month`
  (`game/month_close.py`), fade, and graduation are referenced only by tests; `main.py:64-95`
  lifespan wraps the MCP app only — no scheduler. **Weekly rollups are NOT in this list** —
  `weekly_reveal` is reachable via `routers/game.py:267,277`.
- **BossService no ownership:** `game/boss.py:300-303` `_liab` does `self.db.get(Liability, id)`
  with no `user_id`; `liability_service.py:67-76` shows the correct scoped pattern.

## Preconditions
- A scheduler mechanism: prefer a FastAPI **lifespan background task** that wakes periodically and
  runs idempotent jobs (no new heavy dependency), or APScheduler if already available. Respect
  `settings.killed_features` (paused features must not run).
- The `rebuild.py` path exists for projection rebuilds — reuse it for drift recovery.

## Implementation
1. **Fold-failure visibility & recovery** (`game/folds.py` / `events.py`) — **additive only; do NOT
   touch the watermark.**
   - **Why the watermark must keep advancing:** `events.py:160-171` documents a determinism
     contract — live ingestion **and** `rebuild.py` both advance *every* registered projection to
     the batch/global max, precisely so live and rebuilt watermarks stay identical. "Advance only
     the projections that succeeded" / "hold the failed projection's watermark back" would make live
     and rebuilt state diverge and break idempotent rebuild. **This option is struck — do not
     implement it.**
   - **The fix is a separate health signal.** When a fold raises, record a per-projection failure
     marker in its own KV namespace, e.g. `("_health", projection) -> {"behind_since_event": id,
     "first_error": ..., "count": n}`. The watermark still advances exactly as today; the marker is
     what tells us a projection is stale and needs a rebuild. The marker clears on a successful
     `rebuild`.
   - Keep the guardrail that a fold failure never breaks the finance request path (the marker write
     is itself best-effort and must never raise into the finance path).
   - Add a `GET /game/health/` (or extend an existing diagnostics endpoint) surfacing which
     projections have an open failure marker, and wire a rebuild trigger (reuse `rebuild.py`).
2. **Shared idempotency-key builder** (used by alerts and any future money-mutating game event):
   `idem_key(*, user_id, kind, entity, period)` → embeds user + recurrence/period so distinct
   firings get distinct keys. Refactor `Alert.idempotency_key` (`alerts.py:102`) to include the
   evaluation period (e.g. the `fires_at` month/week, and the recurrence identity). This is the
   bug-class the report calls out — a shared builder prevents it recurring.
3. **Heat per-kind semantics** (`game/heat.py::verified_underspend_cents`): branch on
   `contract.kind`:
   - `cap_vs_baseline`: keep `monthly_cents * target_param // 100` (percentage).
   - `extra_to_boss`: treat `target_param` as cents (an absolute extra-payment target), not a %.
   - `zero_dips`: define winnability explicitly (e.g. underspend measured against zero overdrafts),
     not a structurally unwinnable formula.
   Preserve the invariant: a sweep proposal never exceeds verified underspend. Add asserts/tests.
4. **Production scheduler** (`main.py` lifespan or a `scheduler.py`): a background task that, on a
   cadence (daily tick checking date boundaries), runs `close_month` at month end, weekly rollups
   weekly, and fade/graduation evaluation — all idempotent, all skipping `killed_features`. Make a
   single function `run_due_game_jobs(db, now)` so it's testable without sleeping.
5. **BossService ownership** (`game/boss.py`): pass/verify `user_id` in `_liab` /
   `register_payment` (`select(Liability).where(id==, user_id==)`), matching `liability_service`.

## Tests to add (`server/tests/test_game_*.py`, `test_heat.py`, `test_completion_audit.py`)
- `test_failed_fold_marks_projection_behind`: force a fold to raise; the projection is flagged
  behind (a `_health` marker is recorded) **and** the watermark still advanced to the batch max
  (proving we did not regress the determinism contract); a successful rebuild clears the marker.
- `test_alert_key_distinct_per_period`: two bill-dip alerts on different dates/periods get distinct
  idempotency keys and both fire; the same alert in the same period dedups.
- `test_heat_extra_to_boss_bounded`: an `extra_to_boss` contract produces a sweep proposal in cents,
  not a percentage-inflated value, and never exceeds verified underspend.
- `test_heat_zero_dips_winnable`: a clean (no-dip) month satisfies a `zero_dips` contract.
- `test_run_due_game_jobs_closes_month_idempotently`: at a month boundary, `run_due_game_jobs`
  seals the month once; re-running is a no-op and `/game/outcomes/` is now populated.
- `test_scheduler_respects_killed_features`: with `killed_features="heat"`, heat jobs don't run.
- `test_boss_rejects_foreign_liability`: a liability id not owned by the user is rejected.

## User-centric & edge-case checks
- The user keeps receiving recurring bill/negative-ahead alerts month after month (not just once).
- If a projection drifts, the user (or owner) can *see* it and rebuild, instead of silently wrong
  XP/streak numbers.
- Months actually seal and outcomes appear — features that have buttons produce results.
- Heat never proposes sweeping more than the user truly underspent (no "the game took too much").
- Re-running close_month (e.g. a scheduler restart) doesn't double-seal or change a sealed month's
  shape (idempotent).

## Regression guardrails
- The "fold synchronously with apply" law and best-effort isolation (finance path never breaks)
  must hold — the drift marker is additive, not a new failure mode.
- Don't regress the **known-flaky** concurrency test (memory persfin-v4-substrate-gotchas).
- Run `pytest -q server/tests/test_game_substrate.py server/tests/test_game_sync_fold.py
  server/tests/test_heat.py server/tests/test_challenges.py server/tests/test_campaigns.py
  server/tests/test_expedition.py server/tests/test_game_boss.py server/tests/test_completion_audit.py`.

## Done-when
- [ ] Fold failures are detectable (marker + health endpoint) and recoverable via rebuild.
- [ ] Alert idempotency keys include user + recurrence/period; recurring alerts re-fire.
- [ ] Heat `target_param` interpreted per kind; sweep invariant preserved.
- [ ] A production scheduler runs month-close/rollups/fade/graduation idempotently, honoring kill
      switches; outcomes populate.
- [ ] BossService scoped to the owner; game suite green (flaky concurrency test excepted).