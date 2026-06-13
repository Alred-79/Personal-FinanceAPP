# Step 09 — Game-substrate integrity

## Goal
Fix the game-logic bugs that are real *even single-user*, and give the dormant game jobs a
production entry point so the game features that have live endpoints aren't permanently empty.

## Why it matters (user impact)
Even with one user, these are visible breakages of the gamified layer the user opted into:
- **The *balance* "negative-ahead" alert fires once per database lifetime.** ⚠ **Correction to the
  original framing:** this is NOT true of bill alerts. Bill and goal alerts already embed a period in
  their `entity` — `entity=f"{item['title']}:{item['date']}"` (`alerts.py:184`) and
  `entity=f"goal:{goal.id}"` (`:257`) — and `idempotency_key` deliberately omits `fires_at` so a bill
  doesn't re-fire every evening but next month's bill (new date → new entity → new key) **does**
  fire. The genuine bug is the **balance** alert, whose `entity="balance"` (`:211`) carries **no
  period**, so once "NEGATIVE_AHEAD" fires it is suppressed forever. The fix must target the
  **periodless entities (balance)** and must **NOT** add a period to the bill path — doing so would
  reintroduce the every-evening re-fire the existing code guards against.
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
- **Alert key periodless ONLY for entities without a date in `entity`:** `game/alerts.py:102-108`
  returns `f"alert:{self.type}:{self.entity}"`, recorded via `_record_fired` (`:335-350`). For bills
  (`entity` = `"title:date"`, `:184`) and goals (`entity` = `"goal:id"`, `:257`) the period is
  already in `entity`, so they re-fire correctly across periods — the omission of `fires_at` is
  intentional (`:105-108` comment). The bug is confined to entities whose `entity` has **no** period
  component, i.e. the **balance** alert (`entity="balance"`, `:211`), which is then suppressed
  forever.
- **Heat target_param treated as % for all kinds:** `game/heat.py:158-181`
  (`verified_underspend_cents`) computes `cap_cents = base.monthly_cents * contract.target_param //
  100` **unconditionally** — there is no `if contract.kind` branch, so the single formula is applied
  to all three kinds even though `target_param` is polymorphic: `cap_vs_baseline` → percentage,
  `extra_to_boss` → an absolute cents target, `zero_dips` → not a cap at all. So `extra_to_boss`/
  `zero_dips` sweep proposals are computed against the wrong unit.
- **No production entry point (month-close/fade/graduation):** `close_month`
  (`game/month_close.py`), fade, and graduation are referenced only by tests; `main.py:64-95`
  lifespan wraps the MCP app only — no scheduler. **Weekly rollups are NOT in this list** —
  `weekly_reveal` is reachable via `routers/game.py:267,277`.
- **BossService no ownership:** `game/boss.py:300-303` `_liab` does `self.db.get(Liability, id)`
  with no `user_id`; `liability_service.py:67-76` shows the correct scoped pattern.

## Preconditions
- **Scheduler — DECIDED: Option B, APScheduler** (declarative cron triggers, a job store, less
  hand-rolled date math). **Add `apscheduler` to `Pipfile`** under `[packages]` and re-lock
  (`pipenv lock`) — this project uses **Pipfile/Pipfile.lock**, NOT `pyproject.toml`/`requirements`
  (verified; the original "pyproject.toml/requirements" was wrong). Use `AsyncIOScheduler`,
  started/stopped in the FastAPI lifespan (`main.py:64-95`, alongside the MCP app wiring). Respect
  `settings.killed_features` (a comma-separated string, parsed as in
  `services/game/experiments.py::_seed_from_settings`).
- **⚠ Multi-worker hazard — the in-process scheduler makes single-worker mandatory.** An
  `AsyncIOScheduler` in the lifespan starts **once per worker process**: run two uvicorn workers and
  `close_month`/fade/graduation fire **twice** at the boundary. Idempotency keeps a double-fire
  *harmless in outcome*, but it doubles work and is fragile. This shares the **single-worker
  deployment invariant** with Steps 02/05 — promote it to an enforced startup check or deploy-doc
  requirement, not an inline aside. If multi-worker is ever needed, the scheduler must move to a
  leader-elected/external trigger (out of scope here) — note it for the production backlog.
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
2. **Fix the periodless alert(s), surgically — do NOT blanket-add a period to every alert.**
   - The concrete bug: the **balance** alert's `entity="balance"` (`:211`) has no period, so its key
     never changes and it fires once ever. Fix by giving the periodless entities a period component
     in `entity` (e.g. `entity=f"balance:{period}"` where `period` is the evaluation week/month the
     negative-ahead projection covers), **matching how bills already do it** — not by changing
     `idempotency_key` to append `fires_at` globally. Appending `fires_at` globally would make the
     bill key change daily and re-fire every evening (the `:105-108` comment is the warning).
   - **Audit every `Alert(...)` construction site** for `entity` values that lack a natural period
     (grep the `entity=` kwargs): periodless → fix; already-period-carrying (bills `:184`, goals
     `:257`) → leave alone. Add a test per category (see below).
   - **Shared builder is optional and must preserve current bill/goal behavior.** If you introduce
     `idem_key(*, user_id, kind, entity, period)`, route the *balance* (and any other periodless)
     alert through it, and prove via test that the **bill** key is byte-identical before and after the
     refactor. A shared builder that silently changes the bill key is a regression, not a cleanup.
3. **Heat per-kind semantics** (`game/heat.py::verified_underspend_cents`): branch on
   `contract.kind`:
   - `cap_vs_baseline`: keep `monthly_cents * target_param // 100` (percentage).
   - `extra_to_boss`: treat `target_param` as cents (an absolute extra-payment target), not a %.
   - `zero_dips`: define winnability explicitly (e.g. underspend measured against zero overdrafts),
     not a structurally unwinnable formula.
   Preserve the invariant: a sweep proposal never exceeds verified underspend. Add asserts/tests.
4. **Production scheduler — APScheduler** (new `server/src/scheduler.py` + lifespan wiring in
   `main.py:64-95`):
   - Create an `AsyncIOScheduler`; `start()` in lifespan startup, `shutdown(wait=False)` on
     teardown (next to the MCP app wiring). Guard with `scheduler_enabled: bool` (default True,
     **False in tests** so the suite is deterministic).
   - Register declarative triggers: `close_month` + fade + graduation on a monthly cron
     (e.g. `CronTrigger(day=1, hour=0, minute=5)`); weekly rollups on a weekly cron. (Weekly already
     has a request-path entry via `weekly_reveal`; the cron is for the unattended path.)
   - **Keep scheduling thin:** each trigger calls a pure, testable `run_due_game_jobs(db, now)` (or
     per-job functions) that opens its **own** `SessionLocal()` — the scheduler runs outside any
     request, so there is no `Depends(get_db)` session (same own-session rule as Step 03's
     reconciliation) — runs the idempotent job, commits, closes.
   - Every job skips `settings.killed_features` and is safe to re-run, so a restart or overlapping
     fire can't double-seal.
5. **BossService ownership** (`game/boss.py`): pass/verify `user_id` in `_liab` /
   `register_payment` (`select(Liability).where(id==, user_id==)`), matching `liability_service`.

## Tests to add (`server/tests/test_game_*.py`, `test_heat.py`, `test_completion_audit.py`)
- `test_failed_fold_marks_projection_behind`: force a fold to raise; the projection is flagged
  behind (a `_health` marker is recorded) **and** the watermark still advanced to the batch max
  (proving we did not regress the determinism contract); a successful rebuild clears the marker.
- `test_balance_alert_refires_next_period`: the **balance** "negative-ahead" alert fires in period P,
  then fires again in period P+1 (distinct key) — the actual bug. The same balance alert within P
  dedups.
- `test_bill_alert_key_unchanged`: a bill alert's idempotency key is **identical** before and after
  this step's change (regression guard — proves we didn't reintroduce the every-evening re-fire). A
  bill on a later due date still gets a distinct key and fires.
- `test_heat_extra_to_boss_bounded`: an `extra_to_boss` contract produces a sweep proposal in cents,
  not a percentage-inflated value, and never exceeds verified underspend.
- `test_heat_zero_dips_winnable`: a clean (no-dip) month satisfies a `zero_dips` contract.
- `test_run_due_game_jobs_closes_month_idempotently`: at a month boundary, `run_due_game_jobs`
  seals the month once; re-running is a no-op and `/game/outcomes/` is now populated. (Test the job
  function directly — do **not** start APScheduler in tests; `scheduler_enabled=False` in the suite.)
- `test_scheduler_disabled_in_tests`: with `scheduler_enabled=False`, the lifespan does not start
  APScheduler (no background fires during the suite).
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
- [ ] The **periodless** alert(s) (balance/negative-ahead) re-fire across periods; the **bill** key is
      proven unchanged (no every-evening re-fire regression).
- [ ] Heat `target_param` interpreted per kind; sweep invariant preserved.
- [ ] A production scheduler runs month-close/rollups/fade/graduation idempotently, honoring kill
      switches; outcomes populate. `apscheduler` added to **Pipfile** and locked.
- [ ] Single-worker deployment invariant documented/enforced (shared with Steps 02/05).
- [ ] BossService scoped to the owner; game suite green (flaky concurrency test excepted).