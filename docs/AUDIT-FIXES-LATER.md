# Audit Fixes — DO LATER (deferred architecture, held decisions, low-priority cleanups)

> **For the implementing agent.** These were deliberately deferred from the main remediation
> (`docs/AUDIT-FIXES-NOW.md`) because they are multi-PR rebuilds, depend on a NOW fix landing first,
> were a held product decision, or are low-priority polish. Each item carries enough context to start
> cold. Re-confirm line numbers by symbol — they drift.

## Global context
- **Repo root:** `/Users/adviklall/Documents/projects LOCAL/persFin app/Personal-FinanceAPP`
- **Backend tests:** `./.venv/bin/python -m pytest`. **Frontend:**
  `./node_modules/.bin/tsc -p tsconfig.app.json --noEmit` + `npx vitest run`.
- **Prereqs:** several items assume the NOW fixes already landed (noted per task).
- **RLS:** verify multi-tenant work on the Docker `postgres:16` path with `enable_rls=true` (SQLite no-ops RLS).

---

# Part A — Architectural rebuilds

## L1 — Plaid inbound webhooks (currently poll-only) · MEDIUM→HIGH effort
- **Problem (confirmed):** a repo-wide grep for `webhook` returns **zero** matches in `server/src`. The
  Link token is created with **no** `webhook` URL (`server/src/databridge/plaid_client.py:63-71`), and
  there's no nightly cron driving `sync_all_tokens`. Transactions only sync on manual
  `POST /plaid/sync-transactions/` or at link time. `SYNC_UPDATES_AVAILABLE`, `ITEM_LOGIN_REQUIRED`,
  `PENDING_EXPIRATION`, `ERROR` webhooks are never received → a de-authed item silently stops updating.
- **Why deferred:** new public endpoint + signature verification + dispatch + Link-token change = its own PR;
  the NOW fix **B4** already adds the contained error-handling (re-link notice on `ITEM_LOGIN_REQUIRED`
  surfaced during a poll).
- **Design:**
  1. Add `POST /api/plaid/webhook` (no user-session auth — Plaid calls it). Register the URL on the Link
     token (`link_token_create` `webhook=...`).
  2. **Verify the `Plaid-Verification` JWT:** fetch the key via `/webhook_verification_key/get` (cache by
     `kid`, refetch on miss), verify the **ES256** signature, check `request_body_sha256` matches the
     SHA-256 of the **raw** body, and reject if `iat` is older than ~5 min (replay defense).
  3. Dispatch by `webhook_type`/`webhook_code`: `SYNC_UPDATES_AVAILABLE` → enqueue a background sync for the
     `item_id`; `ITEM_LOGIN_REQUIRED`/`PENDING_EXPIRATION`/`ERROR` → create a re-link/notify `Notification`.
- **Guards / edge cases:**
  - Verify against the **raw** request body (not a re-serialized dict) for the SHA-256 to match.
  - Map `item_id → access token → user` server-side; **trust the payload only for routing**, never for data.
  - **Idempotency:** the same webhook may be delivered more than once — make the sync idempotent (the global
    `plaid_transaction_id` unique index already dedups rows).
  - Return **200 fast** and do work in the background (Plaid retries non-2xx → duplicate deliveries).
  - Handle a webhook for an `item_id` not yet persisted (race at link time) gracefully.
  - Rate-limit the endpoint; never log the verification JWT or access token.
  - **Dev:** Plaid can't reach `localhost` — document using `/sandbox/item/fire_webhook` for tests.
- **Tests:** valid/invalid/expired signature; dispatch routing per code; duplicate delivery is a no-op.

## L2 — Full streaming LLM cost-metering · MEDIUM effort
- **Problem (confirmed):** `server/src/services/assistant_service.py:2950-2952,3119-3146` — `astream_events`
  surfaces **no usage metadata** in the installed `langchain_groq`, so multi-iteration agent tool-calls are
  **unpriced**; only the final streamed `output_chars // 4` is counted. The enforced ceiling is the
  **requests/day** cap (`llm_budget.py:96-122`, which IS atomic/correct); the **dollar** cap is advisory on
  the live path. NOW fix **E3** adds the cheap reservation fixes (imports/receipts/STT) but not this.
- **Design:** price **every** model sub-run.
  1. First verify whether a newer `groq`/`langchain_groq` surfaces usage on `on_chat_model_end` during
     streaming; if so, sum `usage_metadata` per sub-run.
  2. Else, **tiktoken-count** each sub-run's input+output (track per-iteration in the agent loop) and convert
     via `groq_input/output_price_cents_per_mtok` (`settings.py:278-279`).
  3. Reserve conservatively up front (`assistant_max_iterations × expected_output`) and reconcile **down**
     after the turn.
- **Guards / edge cases:**
  - Don't double-count tool iterations vs final output.
  - **Soft-overshoot** (match the requests cap): finish the in-flight turn, block the **next**.
  - tiktoken has no exact llama tokenizer — document the approximation (cl100k is close enough for a cost
    cap); make the multiplier configurable.
  - **Alert on meter failure:** today `record_cost` failure only `log.warning`s (`assistant_service.py:3148`);
    a persistent failure silently disables the $ cap — emit a metric/alert, not just a log line.
- **Tests:** a short prompt that triggers many tool iterations is priced > 1 unit; the $ cap denies the next
  turn; meter failure raises an alert.

## L3 — MCP token isolation: add `aud`/`iss` + per-purpose keys · LOW effort (only when `mcp_enabled`)
- **Problem (confirmed):** auth access tokens, `assistant_action` tokens, and `mcp_capability` tokens are all
  signed with the **same** `jwt_secret_key` and separated **only** by the `typ` claim
  (`server/src/mcp/policy.py:94-117`, `server/src/services/auth_service.py:367-385`,
  `server/src/services/action_tokens.py`). PyJWT rejects `alg=none`, so classic alg-confusion is closed, but
  one missed `typ` check anywhere is a full type-confusion bypass.
- **Design:** give each family a distinct `aud` (e.g. `"session"`/`"assistant_action"`/`"mcp"`) and `iss`;
  require them in every `jwt.decode(..., audience=..., options={"require":["exp","typ","aud"]})`. Ideally
  derive a **per-purpose signing key** from the master secret (HKDF) so leaking one purpose's verification
  context can't forge another.
- **Guards / edge cases:**
  - Backward compatibility: existing tokens lack `aud`. Capability (60s) and action tokens are short-lived,
    so a hard cutover is cheap; for session tokens, roll out with a grace window (accept missing `aud`, then
    enforce) or force re-login.
  - Update **all** verify sites together (auth, action, capability) — missing one defeats the point.
- **Tests:** a capability token can't be replayed as a session token (and vice versa) even with the shared secret.

## L4 — Notification retention + O(n²) detangle/anomaly · MEDIUM effort · **depends on NOW C1**
- **Problem (confirmed):** no prune/retention for `Notification` rows (only cascade on user delete) — e.g.
  `anomaly:{item.id}` (`notification_service.py:158`) is one permanent row per anomalous transaction, growing
  linearly forever. Detangle/anomaly generation is **O(n²)** over the user's full history
  (`matching.py:178-211` nested loop via `_all_match_rows`; `notification_service.py:149-170` rebuilds history
  per item), run nightly per user with no window.
- **Design:**
  1. **Retention job** (under the scheduler, reusing the **C1** `set_tenant` per-user pattern): delete **read**
     notifications older than N days and/or cap rows per user; add a partial index on `(user_id, read, created_at)`.
  2. **Window the scans** to recent activity (e.g. last 90 days; the pairing `DETANGLE_WINDOW_DAYS` already
     implies a short window suffices), or bucket candidates by `(merchant_key, |amount_cents|)` so pairing is
     near-linear instead of all-pairs.
- **Guards / edge cases:**
  - Retention must never delete **unread/actionable** notices; make it idempotent.
  - **Pin current detection outputs on a fixed fixture BEFORE optimizing**, then assert the windowed/bucketed
    version produces identical results for recent data (no silent behavior change).
- **Tests:** retention deletes only old read rows; detangle/anomaly output unchanged on a fixed dataset after
  the rewrite.

## L5 — Plaid pagination restructure: per-page cursor commit · MEDIUM effort · **depends on NOW B1/B2**
- **Problem (confirmed):** `databridge/plaid_client.py:106-117` accumulates **all** pages into memory and
  returns a single final cursor; `plaid_service.py:307` commits `token.cursor` only at the **end**. A large
  initial pull (`cursor=""`) loads the whole item into RAM in one transaction, and any failure re-pulls from
  `""` next time (full history) rather than resuming. (NOW B1/B2 remove the crash/poison-row; this removes the
  re-pull cost and memory blow-up.)
- **Design:** move the `has_more` loop into the service; apply each page and commit `token.cursor` in its own
  transaction **before** fetching the next; on failure, stop and keep the **last good** cursor (resume, not
  restart). Checkpoint large initial historical pulls.
- **Guards / edge cases:**
  - Reconcile per-page transaction boundaries with the existing per-token `begin_nested()` SAVEPOINT in
    `sync_all_tokens`.
  - Idempotency is preserved by the global `plaid_transaction_id` unique index.
  - **Cursor regression under concurrency:** the sync guard is in-memory/per-process — pair this with a
    Postgres advisory lock (`pg_try_advisory_lock(token.id)`) or `SELECT ... FOR UPDATE` on the token row so
    two workers can't race the cursor (see also the single-worker invariant).
  - Keep `test_cursor_persisted` and `test_cursor_passed_on_subsequent_sync` green.
- **Tests:** a failure on page N keeps pages 1..N-1 and the page-(N-1) cursor; the next sync resumes from there.

## L6 — Fernet key-id ciphertext versioning (graceful rotation) · LOW effort · **depends on NOW B3**
- **Problem:** ciphertext prefix is a fixed `enc:v1:` with **no key fingerprint**, so there's no way to know
  which key encrypted a row → no rotation path (B3 only fails-closed in prod + handles `InvalidToken`).
- **Design:** new prefix `enc:v2:<keyid>:`; keep a key map `{keyid: Fernet}` (or `MultiFernet`); decrypt picks
  by `keyid`, encrypt uses the active key. Provide a one-shot re-encrypt command/migration (decrypt-old →
  encrypt-new). Treat legacy `enc:v1:` (no keyid) as the derived/default key for back-compat.
- **Tests:** rotate keys; old ciphertext still decrypts; new writes use the new key; re-encrypt command migrates.

---

# Part B — Held product decision

## L7 — Credit-card balance semantics (M8) · **HELD per product owner — document as known issue**
- **Problem (confirmed):** `routers/plaid.py:103-109` and `plaid_service.py:198-211` store
  `balances.available` uniformly. For credit/loan accounts `available` is **remaining credit**, not money you
  have — it inflates net worth / Safe-to-Spend.
- **Decision:** owner chose **leave balances as-is for now** (avoids a net-worth shift + data backfill).
  Record it in a "Known issues" doc so it isn't mistaken for a bug later.
- **Future fix design (when un-held):** branch on `account["type"]` — store `current` (as a **negated
  liability**) for `credit`/`loan`, `available` for `depository`; apply the **same** rule in both the
  exchange and refresh paths; add a one-time backfill migration; audit `networth_service` and Safe-to-Spend
  aggregation to treat liabilities with the correct sign.
- **Guards (for the future fix):** the exchange path defaults missing balances to `0` while refresh **skips**
  (`value is None → continue`) — unify that too; backfill must be reversible.

---

# Part C — Low-priority cleanups (polish; do when touching the area)

- **SpendTool output skips PII scrub** — `assistant_service.py:501-503`. Numeric-only today (no live leak),
  but breaks the "every tool output is scrubbed before Groq" invariant. Wrap in `_safe_for_llm(...)`.
- **Streamed error handler bare-raises mid-stream** — `assistant_service.py:3098-3110`. A non-rate-limit
  exception raised inside the async generator yields a broken SSE with no `done` frame (client may hang).
  Emit a generic `error` + `done` frame instead of `raise`.
- **`_warn_if_overwriting` unbounded ref key** — `plaid_service.py:908`. The dedup `ref` embeds the full new
  title, so a bank that micro-revises titles stacks notifications. Key on `plaid_txn_id:new_amount_cents` only.
- **`_emit_correction` per-row work** — `plaid_service.py:500,548`. `import json` inside the method + a
  per-row `TxnPosted` lookup. Move the import to module top; batch the lookups.
- **Legacy-plaintext decrypt path** — `plaid_crypto.py:82-85` returns any un-prefixed value verbatim as
  "legacy plaintext." Once migration is complete, add a settings flag to **hard-fail** on un-prefixed values.
- **N+1 queries** — `GET /goals/` (`routers/goals.py:55-58`, one earmark query per goal) and `fetchAccounts`
  (`client/src/store/store.ts:547-582`, one `/transactions` call per account). Batch both.
- **CSRF defense-in-depth** — cookie auth is `SameSite=Lax` (`auth_service.py:309,319`), which already blocks
  cross-site POST, so this is **largely mitigated**. Add a CSRF token only if you want belt-and-suspenders.
- **Conformal correction comment** — if NOW A4 wasn't taken, at minimum fix the misleading "finite-sample
  (k+1) correction" comment in `forecast_sim.py:189-193` (it's computed on `num_sims`, not the calibration count).
- **Process: linters + scanners + CI** — none run today. Add `ruff`, `bandit`, `pip-audit` to `[dev-packages]`,
  a minimal `.pre-commit-config.yaml`, and wire them + the test suite into `.github/` CI. (NOW G2 only untracks
  the `.db.bak` files.)

---

## How to pick up an item
1. Read its NOW prerequisite (if any) and confirm it landed.
2. Re-locate the cited symbols (line numbers drift).
3. Pin current behavior with a test **before** restructuring (esp. L4/L5).
4. For multi-tenant items, verify on the Docker `postgres:16` path with `enable_rls=true`.
5. Keep the full suite + `tsc`/`vitest` green; add regressions; keep `alembic heads` single-headed.
