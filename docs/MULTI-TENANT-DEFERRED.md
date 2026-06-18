# Multi-Tenant Readiness — DEFERRED (do later, per trigger)

> **Audience:** a fresh coding agent with no prior context on this project.
> **Goal:** the work that should **not** be done preemptively. Each item bolts on at the edges without rewriting application logic, so it is cheaper to do *when its trigger fires* than now. Do an item only when its **Trigger** condition is true.
> **Prerequisite:** the foundational changes in `docs/MULTI-TENANT-DO-NOW.md` (Postgres, RLS, state-seams, structured logging) should already be merged. Several items below assume those seams exist.
> **Scope note:** the owner is **not** building a commercial SaaS. So heavyweight commercial compliance (SOC 2 audits, PCI-DSS scope, vendor security questionnaires) is **out of scope**. Keep only the basic hygiene needed to responsibly hold real users' financial data (Item 9).

---

## Shared context you can rely on

- **Backend:** `Personal-FinanceAPP/server/src/` — FastAPI, SQLAlchemy 2.0.x, Python 3.11. Tests: from `Personal-FinanceAPP/` run `./.venv/bin/pytest -q`. Deps in `Pipfile`, installed into `.venv` (no active pipenv shell; `./.venv/bin/pip install <pkg>`).
- **Assumed-done foundation (from DO-NOW):** runs on **Postgres**; **RLS** enforces tenant isolation via `SET LOCAL app.user_id` per request; state lives behind swappable interfaces (`ConversationStore`, a `RATELIMIT_STORAGE_URI` setting, a scheduler leader-gate); structured JSON logging carries `request_id` + `user_id`.
- **Already in the codebase (relevant to deferred items):**
  - **Plaid is integrated** — `plaid-python` dep, `server/src/services/plaid_service.py`, migrations `b1c2d3e4f5a6_plaid_integrity` and `b3c4d5e6f7a8_add_plaid_sync_columns`. Bank-connect is **not greenfield**; Item 3 is *hardening for scale*.
  - **Containerization exists** — `Dockerfile`, `docker-compose.yml`, `.dockerignore` (Item 6 makes it stateless/multi-instance).
  - **Auth is solid** — JWT + bcrypt + revocable refresh tokens (Item 8 adds MFA/lifecycle).
  - **LLM cost tracking is DB-backed** — `llm_usage_cost_cents` table + `llm_budget` helper.
  - **Dates are date-only ISO strings**; there is **no per-user timezone** (Item 2).

---

## Item 1 — Externalize state to Redis (flip the seams)

**Trigger:** you are about to run **more than one app instance** (horizontal scale, rolling deploys, or any load balancer with >1 backend).

**Why deferred:** DO-NOW already built the interfaces with in-memory implementations. With a single instance, in-memory is correct and faster. Redis is pure infra you add when the seam's environment changes.

**What to build:**
- Stand up Redis (managed, e.g. Upstash/ElastiCache, or a compose service for local).
- Provide `RedisConversationStore` implementing the existing `ConversationStore` interface (store message history as JSON; rebuild the agent per request — never serialize the agent object).
- Set `RATELIMIT_STORAGE_URI=redis://...` (slowapi/`limits` supports this with no code change).
- Replace the scheduler leader-gate with a real leader election (PG `pg_try_advisory_lock` or a Redis lock with TTL).
- Optional: a semantic/response cache and an embedding cache (only if cost/latency justify).

**Checks & edge-case tests:**
- [ ] Conversation continuity across instances: start a chat served by instance A, continue on instance B — history is intact.
- [ ] History window (4 turns) and `/clear_history` behave identically to the in-memory impl.
- [ ] **Redis down → graceful degradation**, not a 500 storm (define: read-through fallback, or fail a single request cleanly).
- [ ] **Rate limits are global, not per-instance:** with 2 instances and a 100/day cap, the 101st request across *both* is blocked (proves the shared store works).
- [ ] **Scheduler fires once cluster-wide:** with N instances, a monthly close job runs exactly once; kill the leader mid-run and confirm failover without double-applying (idempotency keys still hold).
- [ ] **Serialization round-trip:** a conversation written by one instance deserializes byte-identically on another (unicode, emoji, long messages, nulls).
- [ ] Lock TTL / expiry: a crashed leader's lock expires and another instance takes over within the expected window.

---

## Item 2 — Per-user timezone

**Trigger:** real users span **multiple timezones** (or a region with DST where day-boundary correctness matters to users).

**Why deferred:** `docs/TIMEZONE-AUDIT.md` concluded the app is consistently *server-local-date* and this is acceptable for a single-region deployment. Financial dates are date-only strings, so there is no data-corruption risk — only that "today" rolls over on the server's clock. It is a genuinely cross-cutting change (~8 boundary sites) with low payoff until users actually span zones.

**What to build:**
- Add a nullable `user.timezone` (IANA string, e.g. `America/New_York`).
- Introduce a single `today_for(user)` helper and route the ~8 `date.today()`/`as_of` boundary sites through it (streak verdict in `routers/game.py`, `spend_service.py` Safe-to-Spend anchor, `scenario_service.py` drift checks, `llm_budget.today_key()`, scheduler close jobs).
- Decide and document how scheduled month/week closes interact with per-user zones (per-user close vs server close).

**Checks & edge-case tests:**
- [ ] A user in `Pacific/Honolulu` and one in `Pacific/Auckland` get correct, *different* "today" for streaks and Safe-to-Spend at the same instant.
- [ ] **DST transition days:** a user in a DST zone has correct day boundaries on spring-forward and fall-back dates (no 23/25-hour-day off-by-one).
- [ ] Null/unset timezone falls back to a documented default (e.g. UTC) without error.
- [ ] Invalid IANA string is rejected at write time.
- [ ] Streak rollover and budget reset happen at the *user's* local midnight, verified across two zones.
- [ ] Idempotency keys remain stable so a close job near a zone boundary cannot double-apply.

---

## Item 3 — Harden Plaid ingestion for scale

**Trigger:** users connect banks at volume, or a single connect pulls **years of transactions** large enough to stress the request path / DB.

**Why deferred:** Plaid already works for the current scale. Turning it into a queue-backed bulk pipeline is additive and only pays off under real volume.

**What to build:**
- Move sync off the request path into a **queue + worker** (e.g. `arq`/Celery). The webhook enqueues; the worker syncs.
- **Idempotent upserts** keyed on Plaid `transaction_id`; handle `pending → posted` transitions and `removed` transactions.
- Cursor-based incremental sync; bounded/backpressured **historical backfill**.
- Encrypt stored Plaid access tokens (ties to Item 9).
- Per-user fairness so one large backfill can't starve others.

**Checks & edge-case tests:**
- [ ] **Idempotency:** replaying the same webhook / re-running a sync produces no duplicate transactions (assert row counts).
- [ ] **Pending→posted:** a pending transaction that later posts updates in place (no duplicate); amount/date changes reconcile.
- [ ] **Removed transactions:** a Plaid `removed` id deletes/voids the local row.
- [ ] **Large backfill:** a multi-year connect (tens of thousands of transactions) completes without timing out the request and without OOM; progress is observable.
- [ ] **Partial failure / retry:** a worker dying mid-sync resumes from the cursor without gaps or dupes.
- [ ] **Re-categorization** and existing rules still apply to ingested rows; RLS-scoped to the owner.
- [ ] **Webhook auth/replay:** forged or replayed webhooks are rejected.
- [ ] Money stays integer cents end-to-end (no float drift on import).

---

## Item 4 — pgvector hybrid semantic retrieval (the RAG tool)

**Trigger:** the corpus of **free-text** content (receipt line items, tax-document text, notes/memos) is large enough that keyword/SQL search misses fuzzy queries users actually ask.

**Why deferred:** the assistant's SQL tool-calling is the correct engine for numeric/aggregate questions and does not need vectors. Semantic retrieval is additive and depends on Postgres (DO-NOW Item 1). Building it before there's a text corpus to search is premature. **Do not route numeric/aggregate questions through vectors** — keep SQL authoritative.

**What to build:**
- `CREATE EXTENSION vector;` add `documents` + `doc_chunks` tables (`embedding halfvec(N)` + HNSW index; `tsvector` generated column + GIN index). RLS on both (scope by `user_id`).
- Embedding source: **local** (`fastembed`, e.g. `bge-small-en-v1.5`) is preferred for PII; hosted (Voyage/OpenAI) only if quality demands and data-residency is acceptable. Cache by content hash.
- Ingestion: chunk receipts/tax-docs/notes (and a templated NL rendering of transactions) → embed → upsert, off the request path (reuse Item 3's worker).
- Query: hybrid SQL (vector KNN + FTS) fused with **Reciprocal Rank Fusion** (`k=60`), metadata prefilter (user, date, tax_year). Optional cross-encoder rerank of the top ~30.
- New agent tool `semantic_search_documents(query, source_type?, tax_year?, top_k=5)` in `assistant_service.py`, results passed through the existing `_safe_for_llm()` scrub and the 40-row cap. System prompt: use it **only** for fuzzy text lookups; SQL tools for any amount/total/count.

**Checks & edge-case tests:**
- [ ] **Routing discipline:** an aggregate question ("how much on groceries in Q2") still uses SQL and returns an *exact* total; the vector tool is not used for it. Add a regression asserting this.
- [ ] **RLS on chunks:** user A's `semantic_search_documents` never returns B's documents, even with a near-identical query.
- [ ] **Hybrid beats either half:** a paraphrase query (semantic) and a rare-exact-token query (keyword) both surface the right chunk; document a small eval set.
- [ ] **Filtered KNN recall:** with a `WHERE user_id=` / `tax_year=` prefilter, HNSW still returns relevant neighbors (watch post-filter recall; verify `hnsw.iterative_scan` if needed).
- [ ] **Embedding cache:** re-ingesting an identical receipt does not re-embed (cache hit by content hash).
- [ ] **Empty/large inputs:** zero documents → tool returns empty gracefully; a very long tax doc chunks without truncation surprises.
- [ ] **PII scrub:** retrieved chunks pass through `_safe_for_llm()`; SSNs/cards never reach the LLM.
- [ ] **Deletion propagation:** deleting a source document removes its chunks/embeddings (ties to Item 9 erasure).

---

## Item 5 — Observability stack

**Trigger:** you launch to real users (any non-trivial multi-user traffic).

**Why deferred:** structured logging (DO-NOW Item 5) covers single-user debugging. The full stack is operational tooling you want *before* real users hit issues, but not before.

**What to build:**
- Error tracking (Sentry) with `request_id`/`user_id` already in scope from DO-NOW.
- Tracing/metrics (OpenTelemetry → your backend of choice; latency, error rate, DB pool, queue depth).
- **LLM cost/latency per tenant** (Langfuse/LangSmith) on top of the existing `llm_usage_cost_cents` data — answer "which users cost what."
- Dashboards + alerts on the daily $-budget breaches and rate-limit saturation.

**Checks & edge-case tests:**
- [ ] A handled and an unhandled error both appear in Sentry with the correct `request_id` and (when present) `user_id`.
- [ ] PII is scrubbed from traces/errors (no SSNs, tokens, raw transaction descriptions).
- [ ] Per-tenant cost attribution matches the `llm_usage_cost_cents` ledger to the cent for a sample window.
- [ ] Alerts fire on a simulated budget breach and on rate-limit saturation.
- [ ] Trace context propagates across the queue boundary (request → worker job).

---

## Item 6 — Stateless containers, multi-instance, autoscale

**Trigger:** you deploy to the cloud for multiple users (anything past the single local/Docker box).

**Why deferred:** the current `Dockerfile`/`docker-compose.yml` work for one box; making them stateless/multi-instance only matters once you scale out. Depends on Items 1 (Redis) and the Postgres compose change from DO-NOW.

**What to build:**
- Switch compose/deploy off the SQLite volume entirely; app instances become **stateless** (no local DB file, no local writes — uploads are already in-memory).
- Run N replicas behind a load balancer; health/readiness probes; graceful shutdown (drain in-flight requests, release scheduler lock).
- Connection pooling for many instances (PgBouncer in **transaction** mode — re-verify the RLS `SET LOCAL` requirement from DO-NOW Item 2 still holds under it).
- CI/CD with migrations gated before rollout; blue-green or canary.

**Checks & edge-case tests:**
- [ ] Kill one of N instances mid-request → LB routes around it; no user-visible error (graceful drain).
- [ ] Rolling deploy with a migration: new+old instances coexist without breaking (backward-compatible migration step).
- [ ] **PgBouncer transaction mode + RLS:** the pooling-leak test from DO-NOW Item 2 passes under PgBouncer specifically.
- [ ] Readiness probe fails when DB/Redis is unreachable so the LB won't send traffic to a broken instance.
- [ ] Scheduler still fires exactly once across the fleet (Item 1 leader election under real replicas).
- [ ] No instance writes to local disk (assert; uploads remain in-memory).

---

## Item 7 — Data partitioning & read replicas

**Trigger:** **measured** load — large tables (transactions = users × years) slow queries, or read traffic needs offloading. Never do this speculatively.

**Why deferred:** premature partitioning adds operational complexity for no benefit until volume is real. Postgres + good indexes go a long way first.

**What to build:**
- Confirm composite indexes on hot paths first (`(user_id, date)` etc.) — often this alone suffices.
- If still needed: partition large tables (by `user_id` hash or by time); consider archival of cold years.
- Read replicas for analytics/report queries; route read-only queries to a replica (mind replication lag for read-after-write).

**Checks & edge-case tests:**
- [ ] Benchmark before/after: the slow query that triggered this is measurably faster; capture numbers.
- [ ] Partition routing is transparent to the ORM (no query returns wrong/partial data across partitions).
- [ ] **Read-after-write:** a user who just added a transaction sees it immediately (don't route that read to a lagging replica).
- [ ] RLS policies apply on every partition.
- [ ] Cross-partition aggregates (yearly totals) remain exact to the cent.

---

## Item 8 — MFA & account lifecycle

**Trigger:** real external users hold accounts (not friends/family you trust implicitly).

**Why deferred:** the existing JWT + bcrypt + revocable refresh tokens are a solid base; MFA and full lifecycle are additive and only matter with untrusted external users.

**What to build:**
- TOTP MFA (and/or WebAuthn) on top of the current login flow.
- Account lifecycle: email verification, password reset, lockout/throttle on failed logins, session revocation UI.
- Decide build-vs-buy: keep the in-house JWT layer, or adopt a provider (Clerk/Auth0/WorkOS/Supabase Auth) — the per-request `current_user` dependency is the seam either way.

**Checks & edge-case tests:**
- [ ] MFA enrollment, challenge, and recovery-code flows; a lost-device recovery path works.
- [ ] Replay/window: a used TOTP code can't be reused; clock-skew tolerance is bounded.
- [ ] Brute-force: repeated failed logins trigger throttle/lockout; doesn't lock out the wrong user (per-account, not global).
- [ ] Password reset tokens are single-use, expiring, and invalidate existing sessions.
- [ ] Refresh-token revocation family still holds (existing behavior) after MFA is added.
- [ ] RLS/authz unchanged: a verified MFA session still only sees its own tenant data.

---

## Item 9 — Data protection: encryption, audit log, erasure

**Trigger:** you hold **other people's** financial data in production (the moment before real-user launch). This is hygiene, not commercial compliance — keep it proportionate.

**Why deferred:** unnecessary while you are the only user; required before you take responsibility for others' data.

**What to build:**
- **Field-level encryption** (via a KMS) for the most sensitive fields (Plaid access tokens, any retained identifiers) so a DB dump alone is not game-over. DB-at-rest encryption comes free from managed PG.
- **Audit log** of security-relevant actions (login, token issue/revoke, data export, deletion) — extend the existing immutability-trigger pattern.
- **Account deletion / right-to-erasure** that purges *all* derived stores, not just primary rows: transactions, tax docs, **vector chunks/embeddings (Item 4)**, conversation history (Item 1), caches, and any backups policy.
- Documented data-retention policy.

**Checks & edge-case tests:**
- [ ] Encrypted fields are unreadable in a raw DB dump; decrypt path works for the app role only; key rotation is possible without data loss.
- [ ] Audit entries are append-only/immutable (cannot be edited or deleted by the app role); cover login, revoke, export, delete.
- [ ] **Erasure completeness:** after account deletion, a sweep finds **zero** residual rows for that user across transactions, tax docs, `doc_chunks`/embeddings, conversation store, and rate-limit/cost counters. Add an automated test that asserts this across every tenant store.
- [ ] Erasure is idempotent and survives partial failure (re-running completes the purge).
- [ ] Deletion respects RLS (a user can only erase their own data; admin path is audited).
- [ ] No PII in logs/traces/error reports (re-verify against the structured-logging scrub).

---

## Quick reference — trigger → item

| If this becomes true… | Do item |
|---|---|
| Running >1 app instance | 1 (Redis), 6 (stateless/multi-instance) |
| Users span timezones | 2 (per-user timezone) |
| Bank connects at volume / years of data | 3 (Plaid hardening) |
| Large free-text corpus, fuzzy queries | 4 (pgvector hybrid retrieval) |
| Launch to real users | 5 (observability), 8 (MFA/lifecycle), 9 (encryption/audit/erasure) |
| Measured query/read load | 7 (partitioning/replicas) |

**Reminder:** none of this is needed for a working single-user app. Pull an item forward only when its trigger is genuinely true.