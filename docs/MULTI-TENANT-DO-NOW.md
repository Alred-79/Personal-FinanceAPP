# Multi-Tenant Readiness — DO NOW

> **Audience:** a fresh coding agent with no prior context on this project.
> **Goal:** make the *pervasive, hard-to-retrofit* changes now — while the app still has one user and disposable data — so a future multi-user launch is a config/infra swap, not a backend rewrite.
> **Out of scope:** anything in `docs/MULTI-TENANT-DEFERRED.md`. Do **not** start deferred work here. If a task tempts you toward Redis, Plaid scaling, pgvector, or a per-user timezone column — stop; that is deferred.

> **Re-assessment (2026-06-18), after the Analytical-Layer commit `138778c`:**
> - Alembic **head is now `f2a9c1d4e7b3_merchant_lifecycle`** (revises `f0a1b2c3d4e5`). The new `merchant_lifecycle` table uses simple column types, carries `user_id` (FK + index) and is **already RLS-shaped** — no new JSONB/trigger porting needed for it.
> - The scheduler now has **6** `CronTrigger` jobs (was 5), still none timezone-pinned — Workstream 4 covers all 6.
> - New analytics services (`audit_service`, `merchant_lifecycle_service`, `forecast_*`) introduce **no** new SQL portability hazards. `audit_service.py:79,103` use Python-side `as_of.strftime(...)` (portable). The only SQL `func.strftime` remains `routers/analytics.py:54`.
> - **Execution status:** Workstreams 3/4/5 and the Workstream-1 *portability prep* are executed and committed, verified on the SQLite suite (1214 passed).
> - **Postgres validation (2026-06-18, Docker `postgres:16`):** the conftest was ported to an optional Postgres target (`TEST_DATABASE_URL`), and the dialect-aware layer was validated on real Postgres — schema builds, the `strftime`→`substr`/ISO-week bucketing returns correct pivots, and the PL/pgSQL **append-only triggers fire** (UPDATE+DELETE blocked). A curated query/schema/trigger subset (151 tests) is green on Postgres. **WS2 RLS** is implemented (`server/src/db/rls.py`) and validated by `test_rls_postgres.py` (tenant isolation, cross-tenant write rejected, unset-context fails closed, transaction-scoped/pooling-safe). Two real bugs the PG run surfaced were fixed: a trigger test that assumed SQLite id-reuse-after-rollback, and the RLS policy crashing on the empty-string a custom GUC reverts to after `SET LOCAL` (fixed with `NULLIF`).
> - **Still pending (not blockers for the seams above):** running the *entire* 1214-test suite on Postgres to 100% green (a long tail of SQLite-only test assumptions, e.g. id-reuse, to fix); the full WS1 data migration (JSONB/TIMESTAMPTZ on existing rows) and the `alembic upgrade head` PG-cleanliness pass (some historical migrations carry SQLite-only trigger DDL); and rolling `enable_rls` + a per-request `set_tenant` across every tenant table and the request lifecycle (the mechanism is proven; the rollout is mechanical).

---

## 0. Why these and not others

The litmus test that selected this list: **a change belongs here only if it bakes an assumption into stored data or into every query/request, making it cheap today and brutal/risky to retrofit across a live multi-tenant system.** Everything else bolts on at the edges later.

**Already done — do NOT redo (verified in code):**
- Real auth: JWT + bcrypt, per-request `AuthService.get_current_user` dependency; every router threads `current_user.id` into the service/query layer. **No hardcoded `user_id`, no "default user."**
- Ownership scoping is consistent across routers/queries (`...user_id == current_user.id`).
- Money is stored as **integer cents** (migration `a1b2c3d4e5f6_money_to_integer_cents`). Do not reintroduce floats.
- Uploaded receipts/tax-docs/statements are processed **in memory and dropped** — nothing written to local disk. No blob-storage retrofit needed.
- Refresh tokens with revocation already exist (migration `c4d5e6f7g8h9_add_refresh_tokens`).
- Dates for financial records are stored as **date-only ISO strings** (`YYYY-MM-DD`), not timestamps. See `docs/TIMEZONE-AUDIT.md`: the classic UTC-vs-local mis-bucketing bug does **not** exist. Do not "fix" it.

---

## 1. Current-state facts you can rely on

- **Backend:** `Personal-FinanceAPP/server/src/` — FastAPI, SQLAlchemy 2.0.x, Python 3.11.
- **DB today:** SQLite. URL default in `server/src/settings.py` (`database_url = "sqlite:///finance_tracker.db"`). Engine built in `server/src/db/session.py` (sets SQLite `PRAGMA` WAL + foreign_keys, `check_same_thread`). **Synchronous** sessions only.
- **Migrations:** Alembic. `alembic.ini` → `script_location = %(here)s/server/migrations`. Real URL comes from `server/migrations/env.py` (which reads settings), **not** from `alembic.ini` (that line is a placeholder). `env.py` currently sets `render_as_batch=True` (a SQLite-only workaround). ~28 migrations exist; baseline revision is `e9a775ab9d6c_baseline_schema`; **current head is `f2a9c1d4e7b3_merchant_lifecycle`**.
- **Single-worker invariant (the thing we are dismantling):** the app must run as one process today because of in-process state — APScheduler scheduler (`server/src/scheduler.py`), slowapi/`limits` rate limiter, and a `cachetools` `TTLCache` holding the per-user LangChain agent + `ConversationBufferWindowMemory` in `server/src/services/assistant_service.py`. This is asserted in `server/src/main.py` and `scheduler.py`.
- **LLM cost tracking** is DB-backed (migration `e5f6a7b8c9d0_llm_usage_cost_cents`, plus an `llm_budget` helper). Verify before assuming it needs externalizing (see Workstream 3).
- **Deps:** declared in `Pipfile` (`[packages]`/`[dev-packages]`), installed into `Personal-FinanceAPP/.venv`. There is no active pipenv shell — add a package by editing `Pipfile` for the record **and** installing into the venv: `./.venv/bin/pip install <pkg>`.
- **Tests:** run from `Personal-FinanceAPP/` with `./.venv/bin/pytest -q`. `pytest.ini` sets `pythonpath = .` and `asyncio_mode = strict`. Fixtures live in `server/tests/conftest.py` and currently use an **in-memory SQLite** engine with `StaticPool`.
- **Containerization already exists** but is SQLite-bound: `Dockerfile`, `docker-compose.yml` (mounts `./data`, sets `DATABASE_URL=sqlite:////app/data/...`). You will update compose in Workstream 1.

---

## 2. Workstreams (do in this order)

1. **Postgres migration** — the foundation; everything else assumes it.
2. **Row-Level Security (RLS) tenant isolation** — rides on #1.
3. **Externalize single-worker state behind swappable interfaces** (no Redis yet — just the seam).
4. **Pin scheduler timezone + standardize date-range convention** (independent; small).
5. **Structured logging with request-id + user-id context** (independent; small).

Land each as its own commit/PR. **After every workstream the full test suite must be green** (`./.venv/bin/pytest -q`).

---

## Workstream 1 — Migrate SQLite → Postgres

**Why now:** trivial migration today (one user, disposable data); a high-stakes live migration after launch. Unlocks RLS, `JSONB`, `TIMESTAMPTZ`, and (later) pgvector.

### Tasks
1. **Driver + deps.** Add `psycopg[binary]` (psycopg 3) to `Pipfile` and install into `.venv`. Keep SQLite working for now as a fallback so you can bisect regressions.
2. **Engine config** (`server/src/db/session.py`): make engine setup **dialect-aware**.
   - SQLite-only bits (`connect_args={"check_same_thread": False}`, the `PRAGMA journal_mode=WAL` / `PRAGMA foreign_keys=ON` event listeners) must run **only** when the URL is SQLite.
   - For Postgres add a real pool: `pool_pre_ping=True`, sensible `pool_size`/`max_overflow`. Foreign keys are enforced natively by PG (no PRAGMA).
3. **Alembic** (`server/migrations/env.py`): make batch mode conditional — `render_as_batch = connection.dialect.name == "sqlite"`. It is currently hardcoded `True` in **two** places (offline `~line 62` and online `~line 86`); fix both. Batch mode on PG is unnecessary and can corrupt `ALTER`s.
4. **Type migrations** (new Alembic revision(s)):
   - **JSON-as-TEXT → `JSONB`.** Find every column that stores JSON in a `String`/`Text` column (e.g. `fields_json`, `map_json`, anything `*_json`). Convert with an explicit cast: `ALTER COLUMN x TYPE jsonb USING x::jsonb`. **Edge:** existing rows may hold `NULL`, empty string `''`, or non-JSON text → the cast will fail. Pre-clean (`NULLIF(x,'')`) and validate before casting.
   - **Naive `DateTime` → `TIMESTAMPTZ`** (`sa.DateTime(timezone=True)`) for stamp columns (created/updated/expiry). **Edge:** existing naive values are interpreted in the session timezone on cast — set `SET TIME ZONE 'UTC'` for the migration so they land as UTC. (These are stamp-only columns per `TIMEZONE-AUDIT.md`; financial *dates* stay `YYYY-MM-DD` strings — do not touch those.)
5. **🔴 SQLite-only SQL/DDL — highest-risk portability items.** Two distinct hazards:

   **(a) `func.strftime` date bucketing.** Used at **`server/src/routers/analytics.py:54`**: `bucket_expr = func.strftime(fmt, model.date)` where `fmt` is one of `%Y-%m` / `%Y-W%W` / `%Y-%m-%d`. **Postgres has no `strftime`.** Because dates are ISO strings:
   - `%Y-%m-%d` → the column itself.
   - `%Y-%m` → `func.substr(col, 1, 7)`.
   - `%Y-W%W` (ISO week) → needs `to_char(to_date(col,'YYYY-MM-DD'),'IYYY-"W"IW')`; verify the week-numbering matches the old `%W` output, or callers will silently regroup data.
   - **Note:** the Python-side `.strftime()` calls in `notification_service.py`, `scenario_service.py`, and `assistant_service.py` operate on Python `datetime` objects, not SQL — they are **portable, leave them alone**. Only the `func.strftime` SQL expression must change.

   **(b) 🔴 SQLite-only trigger DDL (easy to miss).** The codebase enforces append-only / immutability with **raw SQLite triggers using `RAISE(ABORT, ...)`**, which is **not valid Postgres**:
   - `server/src/db/models.py`: `game_events_no_update` and `game_events_no_delete` (`~923–939`, attached via `DDL(...)` + `event.listen`), and `runs_map_json_immutable` (`~949`).
   - Raw trigger DDL also lives inside migrations `e8f9a0b1c2d3_runs.py` and `f6a7b8c9d0e1_game_event_substrate.py`.
   - Port each to a **Postgres PL/pgSQL trigger function** (`RAISE EXCEPTION ...`) — or dialect-guard the DDL so SQLite gets the old form and PG gets the PL/pgSQL form. Do **not** silently drop them: they protect the append-only event log and the immutable run snapshot.

   **(c)** Grep for any remaining SQLite-isms: `INSERT OR REPLACE`, `OR IGNORE`, `PRAGMA`, bare `date()`/`julianday()`, `AUTOINCREMENT`, `sqlite_*`. Replace with portable SQLAlchemy or dialect-guarded expressions.
6. **Test harness** (`server/tests/conftest.py`): run tests against **real Postgres**, not in-memory SQLite, or the migration proves nothing.
   - Recommended: `testcontainers[postgres]` to spin an ephemeral PG per session; create schema via the Alembic migrations (not `create_all`, so migrations are exercised).
   - Isolate tests: wrap each test in a transaction rolled back at teardown, or `TRUNCATE ... RESTART IDENTITY CASCADE` between tests. **Edge:** `StaticPool` single-connection assumptions break on PG — remove them.
7. **Docker/compose**: update `docker-compose.yml` to add a `postgres` service with a named volume, point `DATABASE_URL` at it, and add a `depends_on` healthcheck. Update `.env.example` with the PG URL shape.

### Checks & edge-case tests
- [ ] **Full suite green on Postgres** (`./.venv/bin/pytest -q`) — this is the primary acceptance gate.
- [ ] Suite also still green on SQLite (until you intentionally drop SQLite), to prove dialect-guards work.
- [ ] **`alembic upgrade head` from an empty PG DB succeeds**, then **`alembic downgrade base` then `upgrade head` again** succeeds (round-trip).
- [ ] **Data-shape parity:** dump a representative SQLite row set and confirm the same rows/aggregates after migrating into PG (especially money sums — verify integer-cents totals match to the cent).
- [ ] **JSONB edge cases:** rows with `NULL` json, empty-string json, and deeply nested json all migrate and read back identically; querying a JSONB field (`->>`) returns expected values.
- [ ] **`strftime` replacement parity:** for the same dataset, monthly / weekly / daily buckets from `analytics` produce **identical groupings** pre- and post-migration. Add an explicit regression test asserting the bucket keys. Pay special attention to ISO-week numbering and to records near year/month boundaries (`2025-12-31`, `2026-01-01`).
- [ ] **Trigger/immutability parity on Postgres:** the ported triggers still fire — an UPDATE/DELETE on `game_events` is rejected, and an UPDATE changing `runs.map_json` is rejected (assert the raised error), exactly as on SQLite.
- [ ] **Timestamp edge cases:** a token/expiry written before the migration still compares correctly against `datetime.now(timezone.utc)` after the column became `TIMESTAMPTZ` (no off-by-hours, no naive/aware comparison crash).
- [ ] **Concurrency:** two concurrent requests using separate pooled connections both succeed (the SQLite `check_same_thread` workaround is gone and not silently re-added).
- [ ] **FK enforcement:** inserting a child row with a dangling FK is rejected by PG (parity with the old PRAGMA behavior).
- [ ] **Pool exhaustion:** simulate more concurrent sessions than `pool_size + max_overflow`; confirm graceful queueing/timeout, not a crash.

---

## Workstream 2 — Row-Level Security (RLS) tenant isolation

**Why now:** turning RLS on while there is one user makes any accidentally-unscoped query fail loudly in tests *today*, instead of becoming a silent cross-tenant data leak (IDOR) after launch. It is a permanent correctness net.

### Tasks
1. **Ensure every tenant-owned table carries `user_id`.** Many do. For child tables that today reach the user only via a parent (e.g. an expense → account → user), **denormalize `user_id` onto the child** so RLS policies stay simple and fast. Backfill it in the same migration. **Edge:** keep it correct on future inserts — enforce via app layer and/or a DB trigger; add a `CHECK`/test that child `user_id` always equals parent `user_id`.
2. **Per-request tenant context.** Add a mechanism that issues `SET LOCAL app.user_id = :uid` **at the start of each request's transaction**, derived from `current_user.id`. A SQLAlchemy `after_begin`/session event or a FastAPI dependency wrapping the session is fine.
   - **🔴 Critical (connection-pooling correctness):** it must be `SET LOCAL` **inside the transaction**, never `SET` on the connection. Pooled/PgBouncer-shared connections otherwise leak one user's context into another user's request. This is the single highest-stakes bug in this workstream.
3. **Policies.** `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;` + a `USING (user_id = current_setting('app.user_id')::bigint)` policy (and a matching `WITH CHECK` for writes) on each tenant table.
4. **Admin/migration bypass.** Alembic and any maintenance job must run as a role with `BYPASSRLS` (or RLS forced off for the owner), or migrations will fail. Document the role split.
5. **Verify the assistant still works under RLS** — `server/src/services/read_queries.py` queries must run within a request that has set `app.user_id`.

### Checks & edge-case tests
- [ ] **Cross-tenant read returns empty:** with `app.user_id = A`, a query for B's rows returns nothing — for **every** tenant table, not just transactions.
- [ ] **Cross-tenant write rejected:** attempting to insert/update a row with another user's `user_id` violates the `WITH CHECK` policy.
- [ ] **JOIN safety:** a query joining two tenant tables (e.g. transactions × accounts) returns only the caller's rows even if a crafted ID points at another user's parent.
- [ ] **Missing context fails closed:** if `app.user_id` is unset (e.g. a code path forgot the dependency), queries return zero rows / error — never *all* rows. Add a test that asserts this.
- [ ] **Pooling leak test:** run request-as-A then request-as-B on the *same* pooled connection (force pool size 1); assert B never sees A's context. This directly exercises the `SET LOCAL` requirement.
- [ ] **Denormalized `user_id` integrity:** insert a child row whose `user_id` mismatches its parent → rejected by trigger/check.
- [ ] **Migration role:** `alembic upgrade head` succeeds under the bypass role with RLS enabled on all tables.
- [ ] **Assistant end-to-end:** an assistant chat that calls `get_transactions_by_date_range` returns only the calling user's data with RLS on.

---

## Workstream 3 — Externalize single-worker state (seams only)

**Why now:** every new feature written against in-process state deepens the single-worker lock-in. Build the *interface* now (with the current in-memory implementation behind it) so "go multi-worker" later is swapping an implementation, not refactoring callers. **Do not add Redis now.**

### Tasks
1. **`ConversationStore` interface** for the agent/conversation state in `server/src/services/assistant_service.py`.
   - Today: a `cachetools.TTLCache` keyed by `user_id` holding the LangChain agent + `ConversationBufferWindowMemory` (window = 4; TTL ~30 min — see `settings.py`).
   - Extract an interface: `get_history(user_id)`, `append_turn(user_id, ...)`, `clear(user_id)`. Provide `InMemoryConversationStore` (wraps the existing TTLCache). Route all current call sites through it.
   - **🔴 Nuance:** the LangChain *agent object* is generally not serializable. The store must own **message history only**; the agent should be rebuilt per request from history. Verify the refactor doesn't try to cache an unserializable object in a way that would break a future Redis impl.
2. **Rate-limiter storage URI.** The app uses slowapi/`limits`, which already supports a storage backend URI (`memory://`, `redis://`, …). The `Limiter(...)` is constructed in **`server/src/limiter.py:50`** (a single shared module imported by `main.py` and routers; per-endpoint limits are applied via `@limiter.limit(lambda: settings.…)`). Make the storage URI a setting (e.g. `RATELIMIT_STORAGE_URI`, default `memory://`) instead of hardcoding in-memory. No behavior change today; one-line swap later.
3. **LLM cost/usage budget — already DB-backed; just confirm.** `server/src/services/llm_budget.py` persists per-user daily spend to the DB (`record_cost` / `record_actual` write via a session; `today_key()` is the day boundary; table `llm_usage_cost_cents`). This is **already multi-worker-safe** — no seam needed; add a regression test (below) and note it. **Caveat:** check `release_request` / request-count reservation — if any request counter is held in-process rather than in the DB, give *that* the same storage-URI seam.
4. **Scheduler leader-gate** (`server/src/scheduler.py`). APScheduler runs in-process. Add a `should_run_scheduler()` gate behind a setting (e.g. `SCHEDULER_LEADER=true`) so that when multiple instances run, only one schedules jobs. Document that the real implementation later is a PG advisory lock (`pg_try_advisory_lock`). **Note:** job idempotency keys already make a double-fire harmless (per `TIMEZONE-AUDIT.md`), so this is a lightweight seam, not a hard dependency.

### Checks & edge-case tests
- [ ] **Behavioral parity:** all existing assistant/chat tests pass unchanged after routing through `ConversationStore`.
- [ ] **History window honored:** the 4-turn window still trims correctly via the interface (turn 5 evicts turn 1).
- [ ] **Clear works:** `/clear_history` (or equivalent) empties the store for that user only, not others.
- [ ] **Isolation:** user A's conversation never appears in user B's history (test with two users through the interface).
- [ ] **Serializability guard:** add a test/assertion that what the store persists is plain data (history), so a future Redis/JSON backend can round-trip it. The agent object must be reconstructed, not stored.
- [ ] **Rate-limit setting:** with `RATELIMIT_STORAGE_URI=memory://`, the existing 100-req/day and cost limits behave exactly as before; changing the URI does not require code changes (config-only).
- [ ] **Cost budget:** confirm (with a test) that the daily $-cap counter survives a simulated process restart if it is DB-backed (proves multi-worker safety). If it does not survive, it was in-process — fix the seam.
- [ ] **Scheduler gate:** with `SCHEDULER_LEADER=false`, no jobs are scheduled; with `true`, jobs schedule as before. Two instances with only one leader → each job fires once.

---

## Workstream 4 — Pin scheduler timezone + standardize date-range convention

**Why now:** these are the only *unmitigated* timezone items from `docs/TIMEZONE-AUDIT.md`, and they are cheap. (The full per-user-timezone column is explicitly **deferred** — do not build it here.)

### Tasks
1. **Pin APScheduler triggers to UTC** in `server/src/scheduler.py`: pass `timezone="UTC"` to **all 6** `CronTrigger(...)` jobs (monthly close `day=1,hour=0,minute=5`; weekly Monday; and the daily F2/F3 analytical jobs at `hour=0` minutes 20/30/40/50). Today they are unpinned, so a DST shift could move a job.
2. **Standardize the range convention.** Document the house rule **half-open `[start, nextday)`** for any range that could ever carry a time component, and align the currently-inclusive `<= end` filters: **`server/src/routers/analytics.py:71`** (`model.date <= end.isoformat()`) and **`server/src/routers/transactions.py:39`** (`model.date <= date_to`). Inclusive date-only ranges are *correct* today; the goal is one convention so a future time-bearing column doesn't silently drop the last day. Keep behavior identical for date-only data.

### Checks & edge-case tests
- [ ] Monthly/weekly close jobs fire at the expected UTC instant; add a test asserting the trigger's timezone is UTC.
- [ ] **DST boundary:** simulate a server local DST transition and confirm the close job's scheduled UTC time does not shift.
- [ ] **Idempotency preserved:** a job firing twice (simulated) still no-ops via existing keys (`day:{user}:{date}`, `seal:{user}:{month}`).
- [ ] **Range parity:** for date-only data, the standardized range returns the **same rows** as before (including the last day) — assert against a dataset with transactions on the exact `end` date.
- [ ] **Boundary records:** transactions dated on `start`, on `end`, and one day past each are included/excluded correctly.

---

## Workstream 5 — Structured logging with request-id + user-id

**Why now:** cheap as a clean-slate habit; tedious to retrofit across an existing log surface, and it is the on-ramp every observability tool later plugs into.

### Tasks
1. Add middleware that generates a `request_id` (uuid4) per request and binds `request_id` + `user_id` (when authenticated) into a `contextvars.ContextVar`.
2. Configure logging to emit structured (JSON) lines including those fields. Prefer stdlib `logging` + a `Filter` reading the contextvar, or a light lib — **do not** add a heavy framework.
3. Ensure the bound context propagates to logs emitted deep in the service/query layer without threading args.

### Checks & edge-case tests
- [ ] Every request log line carries a `request_id`; two concurrent requests get **distinct** ids (contextvar isolation under async — test with `asyncio.gather`).
- [ ] **Unauthenticated requests** log with `user_id` absent/null, not a crash.
- [ ] **Background scheduler jobs** (no request scope) log without a `request_id` and without error.
- [ ] An error raised in the service layer logs with the originating request's `request_id`.
- [ ] No PII leaks into logs — reuse the existing scrubbing posture; assert SSNs/tokens never appear in a log line.

---

## 3. Definition of done

- [ ] All five workstreams merged; **`./.venv/bin/pytest -q` green on Postgres** end to end.
- [ ] App boots and serves a full auth → chat → query flow against Postgres locally (`docker-compose up`).
- [ ] No remaining SQLite-only SQL/DDL in application code paths: grep clean for `func.strftime`, `PRAGMA`, `INSERT OR REPLACE`, and `RAISE(ABORT` (ported to PL/pgSQL). Note: Python-side `.strftime()` on `datetime` objects is fine — only `func.strftime` matters.
- [ ] RLS proven to block cross-tenant access in tests, including the pooling-leak test.
- [ ] State seams in place with in-memory implementations; switching any to an external store is config-only.
- [ ] `docs/TIMEZONE-AUDIT.md` "cheap now" items closed (scheduler tz pinned, range convention documented).
- [ ] This file's checklists all ticked, or unticked items explicitly noted with rationale.

**Reminder:** do not pull anything forward from `docs/MULTI-TENANT-DEFERRED.md`.