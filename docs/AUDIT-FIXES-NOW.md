# Audit Fixes — DO NOW (Critical + High + Medium bug fixes)

> **For the implementing agent.** Each task is self-contained: files, the confirmed problem,
> the exact fix, **guards/edge cases**, helpers to reuse, and tests. Apply tasks in the phase
> order at the bottom; keep the suite green between phases.

## Global context
- **Repo root:** `/Users/adviklall/Documents/projects LOCAL/persFin app/Personal-FinanceAPP`
- **Backend tests:** `./.venv/bin/python -m pytest` (1369 tests today — keep them green). Run a
  targeted file with `./.venv/bin/python -m pytest server/tests/test_X.py -q`.
- **Frontend checks:** `./node_modules/.bin/tsc -p tsconfig.app.json --noEmit` (0 errors today) and
  `npx vitest run`.
- **Money convention:** DB stores **integer cents**; API talks **dollar floats**. Convert only at the
  seam via `server/src/money.py` (`dollars_to_cents`, `cents_to_dollars`, `round_half_even_cents`).
- **Line numbers below are HINTS** — they will drift as you edit. Locate by function/symbol name.
- **Add a regression test for every fix.** Do not weaken an existing test to make a fix pass without
  understanding why it changed.
- **RLS note:** RLS only enforces on Postgres; on SQLite (default/test) `set_tenant`/`enable_rls`
  no-op. Multi-tenancy fixes (C1, C2, D1) must be verified on the Docker `postgres:16` path with
  `enable_rls=true`, not just SQLite.

---

## Phase 1 — Quick correctness wins

### A1 — Forecast overdraft pool uses an unordered per-transaction list · **CRITICAL**
- **File:** `server/src/services/forecast_service.py` → `_burn_residual_pool_cents` (~139-146).
- **Problem (confirmed):** the bootstrap pool is built from `_discretionary_amounts_cents` — an
  **unordered, per-transaction** amount list — padded with zeros, then fed to a 7-day moving-**block**
  bootstrap (`forecast_sim.bootstrap_overdraft`) that assumes a **day-ordered daily** series. This
  mis-estimates daily variance and defeats the block bootstrap's day-of-week autocorrelation. The
  correct chronological per-day series already exists: `_daily_discretionary_series_cents` (~150).
- **Fix:** build the pool from the daily series:
  ```python
  series = self._daily_discretionary_series_cents(user_id, as_of, window_days)  # len == window_days
  return [day_total - burn_cents for day_total in series]
  ```
- **Guards / edge cases:**
  - **Keep the activity guard.** Still return `[]` when there's too little history — keep the existing
    `len(amounts) < _BURN_MIN_TXNS or window_days <= 0` check (compute `amounts` only for the count, or
    count non-zero days in `series`). Downstream `bootstrap_overdraft` already maps `[]`→`[0]`.
  - `_daily_discretionary_series_cents` already guards `window_days <= 0 → []` and always returns length
    `window_days` (it seeds `[0]*window_days`). Do **not** re-pad.
  - Both methods use the **identical** SQL filter (`recurrence IS NULL`, same date range) — no scope drift.
  - `burn_cents` is the mean **daily** burn over the same window; an all-zero-spend window yields
    `burn_cents == 0` so the pool is all zeros (safe).
- **Tests:** extend `server/tests/test_forecast_burn.py`. Add: a window with multiple transactions on one
  day collapses to a single daily residual, and `len(pool) == window_days`. Keep
  `test_forecast_reports_overdraft_band_with_seed`, `test_burn_can_flip_will_go_negative`, and all of
  `server/tests/test_forecast_sim.py` green.
- **Done when:** pool is chronological + day-grouped, suite green, new test asserts day-grouping.

### A2 — Rule engine earmarks income/refunds (`allocate`/`roundup`) · **HIGH**
- **Files:** `server/src/services/rule_engine.py` → `run_on_transaction` / `_execute_action` (~236-259).
  Tx-view shape: `server/src/services/plaid_service.py:_run_rules_on_synced` (~605-612) sets `"type"`
  always and `"source_type"` only on income.
- **Problem (confirmed):** Plaid sync runs rules on income too (`plaid_service.py:715`), and `matches([])`
  is match-all (`rule_engine.py:76`). `categorize` is guarded (`tx.get("type") != "expense"`, ~404) but
  `allocate`/`roundup` are not, so a rule with no `type` condition earmarks money off a **paycheck/refund**.
- **⚠ Must preserve W5:** the Tax-Reserve allocate rule *intentionally* fires on
  `type=="income" AND source_type=="self_employment"` (`server/src/services/freelancer_setup.py:223-228`).
  Do **not** blanket-block allocate on income.
- **Fix:** before executing `allocate`/`roundup`, allow income only when the rule explicitly opts in:
  ```python
  has_income_intent = any(c.get("field") in ("type", "source_type") for c in conditions)
  if rule.action_type in ("allocate", "roundup") \
     and tx.get("type") != "expense" and not has_income_intent:
      return 0, "skip_non_expense"
  ```
  `conditions` is the already-parsed rule conditions list in `run_on_transaction`.
- **Guards / edge cases:**
  - `conditions` may be `None`/malformed → it's parsed via `_loads(rule.conditions, [])`; `any(...)` over
    `[]` is `False` → safely blocks accidental income earmarks.
  - Missing `"type"` key → `tx.get("type") != "expense"` is `True` → blocked (safe default); synced tx
    always set `"type"`.
  - **Mirror the existing `"noop"` roundup return semantics** (`rule_engine.py:252-253`) so a skip records
    the same way and **moves no money** (return before `_fund_target`).
  - W5 rule has a `source_type` condition → `has_income_intent` True → still fires. Verify with a test.
- **Tests:** extend `server/tests/test_rule_engine.py`: (a) roundup with empty conditions does NOT fire on
  a synced **income** row; (b) allocate with `source_type==self_employment` STILL fires on income. Keep
  `test_source_type_match`, `test_rule_fires_on_synced_transaction`, `test_allocate_fixed_and_pct` green.

### A5 — `_allocation_cents` pct path truncates with `int()` · **LOW (bundled)**
- **File:** `server/src/services/rule_engine.py:268`.
- **Fix:** `return round_half_even_cents(tx_amount_cents * pct / 100)` (helper at `money.py:41-57`) so the
  money layer rounds one consistent way (banker's rounding) instead of truncating toward zero.
- **Guards:** `pct` is already clamped to `[0,100]`; `tx_amount_cents` ≥ 0. Update the expected value in
  `test_allocate_fixed_and_pct` if it asserts the truncated figure.

### D2 — Tax router commits mid-handler (breaks request-atomicity) · **MEDIUM**
- **File:** `server/src/routers/tax.py` — `db.commit()` at ~187, 202, 303, 358, 404, 438.
- **Fix:** replace each in-handler `db.commit()` with `db.flush()`; `get_db` commits once on success
  (`server/src/db/session.py:100-111`).
- **Guards / edge cases:** before swapping each, **confirm nothing after the commit reads in a separate
  session** or depends on durability (e.g. `learn()` at ~187 — check it doesn't open its own session
  expecting the row committed). If a site genuinely needs an early durable write, leave it and add a
  comment explaining why; otherwise flush.
- **Tests:** keep tax router tests green; add one asserting a forced post-flush error rolls the whole
  request back (no partial write).

### F4 — Two contained store/hook bugs · **LOW (bundled)**
- **`client/src/store/store.ts` → `markNotificationRead` (~1063-1075):** only decrement `unreadCount` when
  the target was actually unread.
  ```ts
  const n = state.notifications.find(x => x.id === notificationId);
  // ...map to read: true...
  unreadCount: n && !n.read ? Math.max(0, state.unreadCount - 1) : state.unreadCount,
  ```
  - **Guard:** if `n` is undefined (not in local list) or already `read`, do **not** decrement.
- **`client/src/hooks/useToast.ts`:** change the effect dependency `[state]` → `[]` (~175-183) and lower
  `TOAST_REMOVE_DELAY` (~line 12) from `1_000_000` to e.g. `4000`.
  - **Guard:** confirm no test asserts the `1_000_000` value or relies on listener re-subscription.
- **Tests:** store test for no over-decrement (pattern in `client/src/__tests__/store/store.test.ts`).

### G2 — Untrack DB backups; add ignore rule · **LOW (bundled)**
- **Fix:** `git rm --cached finance_tracker.db.bak finance_tracker.db.pre-v1.bak` and add `*.db.bak` to
  `.gitignore` (the `*.db` rule misses `.bak`).
- **Guards:** keep the local files (don't delete from disk). History still contains the blobs (schema only,
  0 users today) — a history purge is optional and **not** in scope.

---

## Phase 2 — Plaid sync hardening

### B1 — Modify lookup is account-scoped but the unique index is global · **HIGH**
- **File:** `server/src/services/plaid_service.py` → `_process_modified` (~720-876). Indices are **global**
  on `plaid_transaction_id` (`server/src/db/models.py:195-201, 239-244`); `_process_removed` is already
  global-keyed.
- **Problem (confirmed):** the modify lookup filters on `account_id AND plaid_transaction_id` (~782-794).
  If Plaid reports a modify under a **different** `account_id`, the lookup misses → "treat as new"
  `db.add(...)` (~824-835) → collides with the global index → **IntegrityError aborts the whole token sync**.
- **Fix:**
  1. Key the expense/income lookup on `plaid_transaction_id` **alone** (match the index + the removed path).
  2. When found, if `row.account_id != account_id`, set `row.account_id = account_id` (handle the move).
  3. Wrap the remaining "treat as new" inserts in the existing `_insert_deduped(...)` SAVEPOINT helper
     (~568-583) so a global collision returns `False` instead of raising.
- **Guards / edge cases:**
  - A txn can flip sign (expense↔income) — keep the existing delete-old-table + add-new-table logic;
    just drop `account_id` from the WHERE on both lookups.
  - If `_insert_deduped` returns `False` on the "treat as new" path (already exists globally), **log and
    skip** — do not raise.
  - Don't let the same txn be matched in both expense and income simultaneously — keep expense-first
    precedence as the current code does.
- **Tests:** `server/tests/test_plaid_sync.py` — a "modified" delta under a different `account_id` updates
  the existing row (no duplicate, no crash). Keep `test_sync_modified_*`,
  `test_duplicate_plaid_transaction_id_is_noop`, `test_one_failing_token_does_not_abort_others` green.

### B2 — Hard dict subscripts crash the batch on the newer Plaid payload · **HIGH**
- **File:** `server/src/services/plaid_service.py` — `txn["transaction_id"]`/`txn["amount"]`
  (~665, 667, 760, 769), `txn["name"]`/`txn["date"]` (~683, 703, 803, 827, 845, 866) in `_process_added`
  and `_process_modified`.
- **Fix:** **parse-then-mutate.** At the top of each per-txn iteration, read fields defensively and skip
  bad rows *before any DB mutation*:
  ```python
  plaid_txn_id = txn.get("transaction_id")
  amount = txn.get("amount")
  if plaid_txn_id is None or amount is None:
      log.warning("plaid sync: skipping row missing id/amount"); skipped += 1; continue
  title = _clean_title(txn.get("name"))          # _clean_title already None-safe
  txn_date = txn.get("date")
  if txn_date is None:
      log.warning("plaid sync: skipping row missing date %s", plaid_txn_id); skipped += 1; continue
  ```
- **Guards / edge cases:**
  - `_clean_title(name)` is already `None`-safe (`str(name or "")`) — only the **KeyError** needs fixing,
    so `.get("name")` is enough; no extra `or ""`.
  - **Do the field reads/validation BEFORE mutating `self.db`** so a skipped row never leaves the session
    dirty (the modify path mutates rows directly, with no SAVEPOINT).
  - **Never log the full txn** (PII). Log the `transaction_id` only.
  - Keep a `skipped` counter and surface it in the return/summary so silent drops are visible.
- **Tests:** a malformed row in an `added`/`modified` batch is skipped while siblings persist; the skipped
  count is reported.

### B3 — Fernet key derived from `jwt_secret_key` → JWT rotation bricks all Plaid tokens · **HIGH**
- **Files:** `server/src/services/plaid_crypto.py` (`_fernet`, `decrypt`, ~48-90); decrypt call sites in
  `plaid_service.py` (`get_balance` ~130, `_refresh_balances` ~184, `sync_token` ~258).
- **Problem (confirmed):** with `plaid_token_key` unset the Fernet key is derived from `jwt_secret_key`;
  rotating that (a routine credential rotation) makes every `enc:v1:` token throw `InvalidToken` forever,
  and `sync_token`'s decrypt is unguarded.
- **Fix (contained subset — full key-id rotation is deferred to LATER):**
  1. **Fail closed in production:** in `_fernet()` (lazy, NOT at settings import), raise a clear
     `RuntimeError` when `settings.environment.lower() == "production"` AND `settings.plaid_token_key` is
     unset AND Plaid is configured (`settings.plaid_client_id` present). Keep derivation in dev/self-host.
  2. **Handle `InvalidToken`** at every decrypt boundary (esp. `sync_token`): catch it, create a
     **re-link** `Notification` (dedup `ref=f"plaid_relink:{token.id}"`) for `token.user_id`, and
     `continue`/skip that token — never crash `sync_all_tokens`.
  3. Document the rotation order in `.env.example`: *set `PLAID_TOKEN_KEY` before rotating `JWT_SECRET_KEY`.*
- **Guards / edge cases:**
  - The production check must be **lazy** (inside `_fernet()`), not at module import, or it breaks test
    collection / dev startup.
  - **Never** log the token or the key. The re-link notice references the item, not the secret.
  - `_refresh_balances` already swallows broadly — make its decrypt failure ALSO emit the re-link notice
    (don't just silently skip).
- **Tests:** decrypt failure → re-link notification (not an unhandled raise); production + no key → the
  lazy `RuntimeError`.

### B4 — No timeouts / no error-code differentiation · **MEDIUM**
- **Files:** `server/src/databridge/plaid_client.py` (`Configuration`, ~39-51); `sync_all_tokens` generic
  `"sync_failed"` (`plaid_service.py:405-419`).
- **Fix:**
  1. Set a connect/read **timeout** on Plaid calls. In plaid-python 40.x, pass `_request_timeout=(5, 30)`
     (connect, read) on each `*_get`/`*_create`/`transactions_sync` call, **or** configure the urllib3
     pool on the `ApiClient`. *Confirm the exact mechanism for the installed version before settling on one.*
  2. Catch `from plaid.exceptions import ApiException`, parse `error_code` from the response body
     defensively (the body may be malformed JSON → fall back to generic), and on
     `ITEM_LOGIN_REQUIRED`/`INVALID_ACCESS_TOKEN` create a re-link `Notification` instead of an opaque
     `"sync_failed"`.
  3. Add a **bounded** single retry for `PRODUCT_NOT_READY` (short sleep; this runs in a sync BackgroundTask
     thread, so a brief sleep is acceptable — cap it).
- **Guards / edge cases:** dedup the re-link notice (`ref` per item/token) so repeated failures don't stack;
  never block indefinitely; don't retry non-retryable error codes.
- **Deferred to LATER:** the inbound webhook endpoint (real-time sync + signature verification).
- **Tests:** `test_plaid_sync.py` — an `ITEM_LOGIN_REQUIRED` ApiException yields a re-link notification.

---

## Phase 3 — Multi-tenancy & schema (verify on Postgres)

### C1 — Scheduler batch jobs don't bind the RLS tenant · **HIGH**
- **File:** `server/src/scheduler.py`. Jobs **missing** `set_tenant`: `job_close_month` (~92),
  `job_fade_and_graduation` (~116), `job_check_plan_drift` (~180), `job_detangle` (~208),
  `job_tax_quarterly_reminder` (~238), `job_auditor` (~312), and the per-user loop inside
  `run_weekly_rollups` (`server/src/services/game/metrics.py:228`).
- **Problem (confirmed):** with `enable_rls=True` and the default `scheduler_database_url=None`, these jobs
  run with an **unset** tenant GUC → RLS matches **zero rows** and `WITH CHECK` rejects inserts; the
  per-user `try/except` swallows it, so month-close/auditor/detangle/drift/tax silently do nothing.
- **Fix:** apply the **existing** per-user pattern (copy from `job_action_reflection` ~379-399 /
  `_run_behavioral_per_user` ~475-495) inside each user loop:
  ```python
  from .db.rls import set_tenant
  for user in _users(db):
      set_tenant(db, user.id)
      _uid = user_id_var.set(str(user.id))
      try:
          ...  # the per-user work
      except Exception:
          log.exception(...)
      finally:
          user_id_var.reset(_uid)   # LOAD-BEARING — prevents contextvar leak
  ```
  Add the missing per-user `try/except` to `job_check_plan_drift` and `job_detangle`. For
  `run_weekly_rollups`, call `set_tenant(db, user_row.id)` at the **top of its user loop body** (covers both
  the metric computation and the per-user `MetricRollup` writes).
- **Guards / edge cases:**
  - The `finally: user_id_var.reset(...)` is mandatory in every job (prevents the contextvar leaking to the
    next user/request).
  - On SQLite `set_tenant` no-ops → the test path is unchanged; verify `test_game_scheduler.py` stays green.
  - `run_weekly_rollups`'s metric helpers (`hard_day_action_rate`, `alert_fix_rate`) write **per-user**
    rollups, so computing them under each user's tenant is correct — confirm they don't intentionally need
    a cross-user view.
  - **Belt-and-suspenders:** in `start_scheduler` (~829-851), if `settings.enable_rls` is True and
    `scheduler_database_url` is unset, log a hard warning (the BYPASSRLS seam already exists in
    `_scheduler_sessions` ~563-585).
  - Prefer inlining the pattern per job (lowest risk) over force-fitting every job through one shared
    driver — the multi-step jobs (close_month, fade/graduation) don't fit the `runner/accumulate` shape.
- **Tests:** add a Postgres-path test (mirror `server/tests/test_rls_postgres.py`) asserting each batch job
  writes the expected rows under `enable_rls=True`. Keep `test_game_scheduler.py` green.

### C2 — `TaxTag` upsert reassigns ownership + global uniqueness (latent IDOR) · **MEDIUM**
- **Files:** `server/src/services/tax/tagging_service.py` (upsert ~144-158); constraint
  `server/src/db/models.py:1447` (`UniqueConstraint("tx_type","tx_id")`).
- **Fix:**
  1. Add `TaxTagORM.user_id == user_id` to the upsert lookup and **remove** the
     `existing.user_id = user_id` reassignment.
  2. Change the constraint to `UniqueConstraint("user_id","tx_type","tx_id", name="uq_tax_tag_user_tx")`.
  3. Add an Alembic migration (template: `server/migrations/versions/d8e9f0a1b2c3_auto_execute_threshold.py`
     — uses `batch_alter_table` for SQLite). Find the current head with `./.venv/bin/alembic heads`.
- **Guards / edge cases:**
  - SQLite can't drop/alter a constraint in place → use `batch_alter_table` (recreate). Include a
    `downgrade()`.
  - Verify no pre-existing rows violate the new constraint before adding it (today `tx_id` is globally
    unique per table, so duplicates shouldn't exist — assert in the migration or check first).
  - Confirm all callers pass `user_id` (the HTTP caller already prechecks ownership at
    `routers/tax.py:170`).
- **Tests:** tagging a tx never overwrites another user's tag; per-user uniqueness holds; tax tests green.

### D1 — `users.spend_warning`/`savings_percent` nullable mismatch → 500 on a migrated DB · **HIGH**
- **Files:** `server/src/db/models.py:54-55` (NOT NULL via `Mapped[int]`, no `server_default`) vs
  `server/migrations/versions/e9a775ab9d6c_baseline_schema.py:43-44` (`nullable=True`).
- **Fix:**
  1. Add `server_default="20"` / `server_default="10"` to the two ORM columns (copy the
     `auto_execute_threshold_cents` pattern at `models.py:81-83`).
  2. Add a migration that **backfills NULLs first**, then sets the default + NOT NULL:
     ```python
     op.execute("UPDATE users SET spend_warning = 20 WHERE spend_warning IS NULL")
     op.execute("UPDATE users SET savings_percent = 10 WHERE savings_percent IS NULL")
     with op.batch_alter_table("users") as b:
         b.alter_column("spend_warning", nullable=False, server_default="20")
         b.alter_column("savings_percent", nullable=False, server_default="10")
     ```
- **Guards / edge cases:**
  - **Backfill BEFORE `SET NOT NULL`** or the ALTER fails on existing NULL rows.
  - Use `batch_alter_table` for SQLite; include the `_has_column` idempotency guard from the template and a
    `downgrade()`.
  - The ORM `server_default` addition does not change `create_all` NOT NULL (already NOT NULL) — it only
    adds the DEFAULT clause so non-ORM inserts get a value.
- **Tests:** a user row inserted without these columns loads via `read_queries.query_user` with no Pydantic
  error; `./.venv/bin/alembic upgrade head` succeeds on a DB seeded with NULLs.

---

## Phase 4 — Assistant safety & cost

### E1 — Advice firewall bypassable by splitting a phrase across a sentence boundary · **HIGH**
- **File:** `server/src/services/assistant_service.py` streamed path (~3060-3090).
- **Problem (confirmed):** the stream screens **one sentence at a time** (`screen_output(sentence)`), with
  no cumulative pass, so advice split as `"You should.\nBuy crypto."` slips through.
- **Fix:** screen a **rolling cumulative window** before emitting each sentence, and screen the **full
  assembled output** once before the final `done`:
  - keep a `screened_text` accumulator; before yielding a `sentence`, run
    `screen_output(<trailing window of screened_text> + sentence)` and block if it trips.
  - use a trailing window of ~3–4 sentences (bounds cost while catching cross-sentence splits).
  - reuse the existing `soften_tax_narration` + `screen_output(..., plain=True)` calls and the existing
    blocked-path behavior (emit `verdict.safe_text`, then sources, then `done`, then return).
- **Guards / edge cases:**
  - Run the cumulative screen **before** the `yield` for that sentence (after a yield it's already on the
    wire — the inherent streaming limit; the trailing window + final full-text screen are the pragmatic
    mitigation). Note in a comment that a hard guarantee needs buffer-all-then-screen.
  - Keep `tax_soften` applied **before** screening (existing order).
  - Re-screen the trailing `buffer` (partial last sentence) as today.
- **Tests:** extend the firewall tests — `"You should.\nBuy crypto."` is blocked on the streamed path; a
  legitimate tax summary still streams through.

### E2 — LLM/statement extraction writes ORM money rows bypassing the `_MONEY` bounds · **HIGH**
- **Files:** `server/src/services/extraction_utils.py` (`parse_amount` ~22-46);
  `server/src/services/reconciliation_service.py` (`_normalize`/`_to_extraction` ~254-300).
- **Problem (confirmed):** `parse_amount` returns any float with no magnitude/finiteness ceiling; the
  normal-row branch then does `dollars_to_cents(raw.amount)` directly (bypassing the API's `_MONEY` bound
  `allow_inf_nan=False, ±1e12` at `server/src/models.py:33`). There's also no row-count cap in the loop.
- **Fix:**
  1. In `parse_amount`, after parsing, **reject non-finite and out-of-range**:
     ```python
     import math
     if not math.isfinite(v) or abs(v) > 1_000_000_000_000:
         return None
     ```
     Returning `None` routes the row into the existing **exception** branch (the normalizer already creates
     a `status="exception"` row when `amount is None` — see `reconciliation_service.py` ~285-294), so no
     absurd figure is imported. Consider a distinct `reason="out_of_range"` on that branch.
  2. In the transactions loop, **cap row count** (e.g. 2000). If exceeded, stop and surface a truthful
     "truncated N rows" flag to the user — **do not silently drop**.
- **Guards / edge cases:**
  - A present-but-rejected value must become an **exception row**, not a silent `0`. (The current
    `dollars_to_cents(...) if not None else 0` only populates the field on an *already-exception* row — fine,
    but make sure your reject path goes through that branch.)
  - Don't change the behavior for legitimately small/normal amounts.
- **Tests:** `server/tests/test_import_service.py` — an extracted `1e308`/over-`1e12` amount becomes an
  exception row; an over-cap document is truncated-with-flag, not silently imported.

### E3 — LLM budget under-counts on ingestion; receipts/STT have no budget · **MEDIUM**
- **Files:** `server/src/routers/imports.py:131-146` (reserves 1 unit for **2** paid Groq calls);
  `server/src/routers/receipts.py` + `server/src/routers/assistant.py:136-182` (no `llm_budget` at all).
- **Fix:**
  1. `import_extract`: reserve `requests=2` (classify + extract) and **refund** on the early
     `TaxFormDetected`/`ValueError` paths.
  2. Add `llm_budget.check_and_reserve(...)` (with **refund-on-failure**, mirroring `_run_extract`) to
     `scan_receipt` (receipts router) and `/transcribe/` (assistant router).
- **Guards / edge cases:**
  - Put reservations in the **routers only**. The import path calls `ReceiptService.extract` **directly**
    (service layer), so keeping reservations out of services avoids double-counting when import reuses the
    receipt extractor.
  - Reserve **before** the paid call; refund inside the `except` so a failed scan/transcription doesn't burn
    budget.
- **Deferred to LATER:** the full streaming cost-metering rework (M1).
- **Tests:** budget reserve/refund counted correctly for imports, receipts, STT.

### E4 — Flip the MCP pre-auth IP throttle default on · **MEDIUM**
- **File:** `server/src/settings.py:385` → `mcp_preauth_rate_limit_enabled: bool = True`.
- **Why:** lets a bad-key flood be shed before the DB lookup (`mcp/server.py:97-107`). Only affects
  deployments with `mcp_enabled=true`.
- **Guards:** update any `test_mcp_*` that assumed the default was off.
- **Deferred to LATER:** capability-token `aud`/`iss` + per-purpose keys.

---

## Phase 5 — Frontend

### F1 — Unify the two auth-refresh paths · **MEDIUM**
- **Files:** `client/src/lib/api.ts` (axios `isRefreshing`/`failedQueue` mutex, ~25-85);
  `client/src/hooks/useAssistantChat.ts` (raw-`fetch` `refreshAuth()`, ~6-16).
- **Fix:** export a single `refreshOnce(): Promise<void>` from `api.ts` that dedupes concurrent refreshes
  (one shared in-flight promise); have **both** the axios interceptor and the SSE hook call it.
- **Guards / edge cases:**
  - `refreshOnce` must collapse concurrent callers onto the **same** promise; reset it after settle.
  - On the SSE path, after `refreshOnce()` resolves, retry the stream fetch **at most once** (guard against
    an infinite refresh→retry loop).
  - On refresh failure, surface the existing logout/redirect path consistently. `lib/voice.ts` already uses
    axios — leave it.
- **Tests:** concurrent 401s trigger exactly one refresh (mock `api`).

### F2 — Reconciliation patches race on every keystroke · **MEDIUM**
- **Files:** `client/src/components/custom/Reconciliation/ReconciliationReview.tsx` (`patch`, ~57-67;
  onChange handlers ~156-178); `client/src/store/store.ts` (`patchImportRow`, ~653-660, no abort).
- **Fix:** stop PATCHing on every keystroke. Commit text/number/date edits **onBlur** (simplest, race-free),
  or debounce ~400ms; keep checkbox (`included`) and the category select immediate. Add a **per-row
  in-flight token** so only the latest response calls `onSessionChange`.
- **Guards / edge cases:**
  - Clear any debounce timer on unmount.
  - Because `onSessionChange(next)` replaces the **whole** session, an out-of-order older response must be
    ignored (the in-flight token handles this).
- **Tests:** rapid edits issue one settled PATCH; a slow earlier response can't overwrite a newer edit.

### F3 — SSE stream has no AbortController / unmount cleanup · **MEDIUM (bundled)**
- **File:** `client/src/hooks/useAssistantChat.ts` (`send()` reader loop, ~66-191).
- **Fix:** create an `AbortController`, pass `signal` to the stream `fetch`, store it in a ref, and abort on
  unmount via `useEffect(() => () => controller.abort(), [])`; bail the `reader.read()` loop on abort.
- **Guards / edge cases:**
  - Distinguish `AbortError` from a real error — treat abort as normal cancellation (no error toast).
  - Reset `busyRef`/loading state on abort so a remount can send again.
  - Don't `setState` after unmount (the abort + loop bail prevents it).
- **Tests:** unmounting mid-stream aborts the fetch (mock reader).

---

## Phase 6 — Process / supply chain

### G1 — Python version + lockfile drift · **MEDIUM**
- **Problem (confirmed):** venv/pyright run **3.13.7**; `Pipfile` (`python_version="3.11"`) and the Docker
  runtime (`python:3.11-slim`) target **3.11**; `Pipfile.lock` is **gitignored** (no reproducible Python deps).
- **Fix:** pick ONE Python and align `Pipfile`, `Dockerfile`, `pyrightconfig.json`, and CI. **Recommend
  standardizing on the working local 3.13** (tests already pass on 3.13; bump Dockerfile to
  `python:3.13-slim` and `Pipfile` to `3.13`) — *unless* you must keep 3.11 for pymc-marketing, in which
  case recreate the venv on 3.11 and re-run the suite. Then **un-ignore and commit `Pipfile.lock`** (remove
  the `Pipfile.lock` line from `.gitignore`; `git add -f Pipfile.lock`).
- **Guards / edge cases:** if you bump Docker to 3.13, rebuild the image and run the full suite + an
  `alembic upgrade head` inside it before merging. pymc 6.0.1 is already installed and green on 3.13 locally.

---

## Suggested order
Phase 1 → 2 → 3 → 4 → 5 → 6. Run `./.venv/bin/python -m pytest` after each backend phase and
`tsc + npx vitest run` after Phase 5. Verify Phase 3 (C1/C2/D1) on the Docker `postgres:16` path with
`enable_rls=true`, and confirm `./.venv/bin/alembic heads` is single-headed after adding C2/D1 migrations.

## Final acceptance
- All 1369 backend tests + new regressions green; `tsc` 0 errors; `npx vitest run` green.
- `alembic upgrade head` succeeds on fresh SQLite **and** Postgres; single migration head.
- Manual smoke (optional): cross-account "modified" delta (B1), a malformed import row (E2), an
  advice-split assistant reply (E1), and a scheduler run under `enable_rls=true` writing rows (C1).
