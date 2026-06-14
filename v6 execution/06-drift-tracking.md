# 06 — Plan-of-record drift tracking

> Sequential execution doc 6 of 8. Requires docs 01-05 green. Completes the backend.

## Context
A committed plan is monitored: a scheduled job re-evaluates each active plan vs its locked snapshot
and fires a deduped notification on meaningful drift. Reuse the `Notification.ref`/`type` dedup
columns for idempotency.

**Premise correction:** the scheduler does NOT currently generate notifications. `scheduler.py`
registers only the two game ticks (`_monthly_tick`/`_weekly_tick` → `run_due_game_jobs`); notifications
today are produced by the rule engine on transactions, not on a cron. This drift job is therefore the
**first notification producer in the scheduler** — it does not sit "alongside" an existing one. It must
follow the same own-session + idempotent pattern the game jobs use (`_run_in_own_session`: open
`SessionLocal()`, run, commit, close; never crash the scheduler loop).

## Tasks (test-first)
1. **`server/tests/test_scenario_drift.py`**: committing locks a snapshot; degrading reality past a
   threshold produces ONE `Notification(type="plan_drift", ref=f"plan_drift:{plan_id}:{period}")`;
   a re-run does not duplicate (ref dedup); within-threshold drift fires nothing; `last_checked_at` is
   set.
2. **`ScenarioService.check_drift(user_id, as_of=None)`**: for each `status="active"` PlanOfRecord,
   `evaluate` current reality (EMPTY overlay = live) and compare against `baseline_snapshot_json`; if a
   tracked metric drifts past threshold (overdraft_probability rise beyond X, or a goal reach date slip
   > N days), insert the notification; set `last_checked_at`. Keep the job light:
   `include_outlook=False` and a fixed seeded `rng`. (NOTE: confirm whether `forecast()` actually
   exposes a tunable `num_sims` before relying on it — at plan time it does not appear in the signature;
   if the sim count is a module constant, drop that lever and lean on `include_outlook=False` + active-only
   scope instead.)
3. **Add a NEW scheduled job to `server/src/scheduler.py`** — the first notification producer in the
   scheduler (see Premise correction). Register it like `game_weekly` (declarative `CronTrigger`,
   `replace_existing`, `misfire_grace_time`, `coalesce`), run it through `_run_in_own_session`, scope it
   to `status="active"` plans only, with a gated cadence.

## Verification checks
- [ ] `./.venv/bin/pytest server/tests/test_scenario_drift.py server/tests/test_notifications.py -q` → green.
- [ ] `./.venv/bin/pytest server/tests/test_game_scheduler.py -q` → green (scheduler still sound).
- [ ] Backend regression at this milestone: `./.venv/bin/pytest -q` → green. (Baseline at v6 start was
      exactly 863; the real gate is "all prior tests + every test added in docs 01–06 pass" — 863 is a
      floor that is already stale after doc 01, not a target.)

## Risks
- **R7 (job cost):** active-only scope, cheap sim path, gated cadence.
- Notification dedup correctness — pinned by the no-duplicate `ref` test.
- **R8 (new scheduler producer):** this is the first notification job in the scheduler — it must use
  the own-session/idempotent pattern (`_run_in_own_session`) so a failure can't crash the loop and an
  overlapping fire can't double-notify (the `ref` dedup is the second line of defence).
