# Step 03 — C3 Plaid link-token auth + C4 LLM denial-of-wallet

## Goal
Close two criticals: **C3** (the unauthenticated Plaid link-token endpoint that mints tokens with
real credentials from a caller-supplied `user_id`) and **C4** (the LLM chat endpoint with no rate
limit, no cost budget, and an `AgentExecutor` with no iteration/time caps).

## Why it matters (user impact)
- **C3:** `/plaid/link-token/` calls your real Plaid client with a `user_id` *the caller chooses*.
  Anyone on the network can mint Link tokens against your Plaid app — burning your sandbox/prod
  quota and, worse, attaching a Plaid Link session to an arbitrary id. The legitimate user never
  benefits from this being open; the connect flow already happens *after* login.
- **C4:** the assistant is the single most expensive surface in the app. A user who leaves a tab
  looping, or a buggy client retry, can rack up paid Groq + Tavily calls with no ceiling. A
  finance-app owner is precisely the person who will be upset by a denial-of-wallet bill. Caps make
  the feature safe to leave on.

## Findings closed (with evidence)
- **C3:** `server/src/routers/plaid.py:40-44` — `async def get_link_token(user_id: str)` has **no**
  auth dependency and takes a raw `user_id` query param. (Every other plaid route uses
  `Depends(AuthService.get_current_active_user)`.)
- **C4 (no limit/budget):** `server/src/routers/assistant.py:20-26` — `chat` has no
  `@limiter.limit` and no budget call.
- **C4 (no executor caps):** `assistant_service.py` builds `AgentExecutor(agent, tools, memory,
  verbose)` with no `max_iterations` / `max_execution_time` (also `verbose=True` leaks prompts to
  stdout — note for backlog).

## Preconditions
- Step 02 merged: `settings.assistant_rate_limit`, `llm_budget.check_and_reserve/record_actual`,
  proxy-aware limiter, `assistant_max_iterations`, `assistant_max_execution_seconds`.

## Implementation
1. **Authenticate the link-token endpoint** (`plaid.py::get_link_token`):
   ```python
   @router.get("/link-token/")
   async def get_link_token(
       current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
   ):
       link_token = PlaidClient().create_link_token(str(current_user.id))
       return {"link_token": link_token}
   ```
   Drop the `user_id` param entirely; derive it from the session. The Plaid `client_user_id` must
   be stable per user — `str(current_user.id)` is.
2. **Rate-limit + pre-flight budget check at the endpoint** (`assistant.py::chat`):
   - Add `request: Request` and `@limiter.limit(settings.assistant_rate_limit)`.
   - **Pre-flight only** — before returning the `StreamingResponse`, call
     `llm_budget.check_and_reserve(db, current_user.id, est_tokens=<rough estimate>)` using the
     endpoint's `Depends(get_db)` session. On `BudgetExceeded`, return HTTP **429** with a clear
     body (not a mid-stream error). This is the only budget call that may use the request `db`.
3. **⚠ Reconciliation must NOT use the request session.** `chat` is `async def -> AsyncGenerator`
   (`assistant_service.py:1002`); the endpoint returns a `StreamingResponse` and FastAPI tears down
   the request-scoped `Depends(get_db)` session **before** the generator finishes streaming. So
   `record_actual(...)` cannot use the endpoint's `db` — it would be a use-after-close. Run
   reconciliation **inside the generator** with its **own** `SessionLocal()`, opened and closed
   within the generator (the exact pattern the Plaid background task already uses,
   `plaid.py:~100-112`):
   ```python
   async def chat(self, user, message):
       ...
       try:
           # stream tokens ...
       finally:
           db2 = SessionLocal()
           try:
               llm_budget.record_actual(db2, user.id, tokens_used)  # 0 if nothing spent
               db2.commit()
           finally:
               db2.close()
   ```
   The pre-flight reservation (step 2) covers the cap; this reconciles the estimate to actual after
   streaming. If the stream errors before any token, `record_actual(..., 0)` (or reconcile the
   reservation back down) so a failed request doesn't permanently consume budget.
4. **Executor caps + cache invalidation** (`assistant_service.py`): pass
   `max_iterations=settings.assistant_max_iterations`,
   `max_execution_time=settings.assistant_max_execution_seconds`,
   `handle_parsing_errors=True` to `AgentExecutor` at construction (`:1047`). **Note the executor is
   cached per-user in a `TTLCache` (`self.agents`, `:963`)** — caps only apply to newly-built
   executors. A long-lived process keeps capless executors for already-active users until the TTL
   (1800s) expires. If that matters operationally, bump the cache or rebuild on deploy; for tests,
   the cache **must** be cleared/bypassed (see test note) or it reads a stale capless instance.

## Tests to add
`server/tests/test_assistant_search.py` / `test_assistant_writes.py` (whichever has the client),
plus the Plaid suite:
- `test_link_token_requires_auth`: GET `/plaid/link-token/` **without** auth → 401; the old
  `?user_id=` form is no longer accepted (FastAPI returns 401 before reading params).
- `test_link_token_uses_session_user`: authed GET returns a token; assert `create_link_token` was
  called with `str(user.id)` (monkeypatch `PlaidClient.create_link_token` to capture the arg).
- `test_chat_rate_limited`: use the Step 02 `rate_limited` fixture (flip `limiter.enabled`, **not**
  the setting), set `assistant_rate_limit="1/minute"`; second chat call → 429.
- `test_chat_over_budget_returns_429`: set `llm_daily_token_budget` tiny; pre-fill usage to the
  cap; chat → 429 with a readable detail; assert no Groq call was attempted (monkeypatch the agent
  to raise if invoked). Works because the cap is a **pre-flight** check on the request session.
- `test_executor_receives_caps`: **clear the executor cache first** (`assistant_service.agents.clear()`
  or use a fresh `AssistantService`), then trigger a chat and assert the newly-built `AgentExecutor`
  has `max_iterations`/`max_execution_time` from settings — else a cached capless instance false-passes.
- `test_reconciliation_uses_own_session`: pin the use-after-close fix — monkeypatch `SessionLocal`
  to a counting factory and assert reconciliation opens its **own** session (not the request `db`),
  and the budget row is updated even though the request session is already closed.
- `test_budget_not_consumed_on_pre_llm_failure`: force the stream to error before any token; assert
  the day's usage reconciles back to ~0 (no permanent consumption).
- Update any existing Plaid test that called `/plaid/link-token/?user_id=...` to the authed form.

## User-centric & edge-case checks
- The 429 (rate) and 429 (budget) responses carry **distinct, human messages** ("too many requests,
  try again later" vs "daily AI limit reached") so the user knows whether to wait minutes or until
  tomorrow.
- Rate limit must trip **before** the stream starts — a half-open SSE stream that then 429s is
  confusing; assert the limiter rejects at the endpoint, not mid-generator.
- Executor time cap (`max_execution_time`) protects against a tool (Tavily/website fetch) hanging —
  the user gets a bounded "I couldn't finish that" instead of a spinner forever.
- `handle_parsing_errors=True` so a malformed tool call surfaces as a graceful message, not a 500.

## Regression guardrails
- The known-flaky MCP concurrency test is unrelated — don't chase its flake (memory
  persfin-v4-substrate-gotchas).
- Confirm the SSRF guard in `open_website` still blocks private IPs after any executor changes
  (run `test_assistant_security.py`).
- Full `pytest -q server/tests/test_assistant_*.py server/tests/test_plaid_sync.py`.

## Done-when
- [ ] `/plaid/link-token/` requires auth and derives the user from the session; `user_id` param gone.
- [ ] `/assistant/chat/` is rate-limited and budget-gated; over-cap → clean 429.
- [ ] `AgentExecutor` has iteration + time caps; usage reconciled to budget.
- [ ] New tests green; no plaintext `user_id` accepted; assistant security tests still pass.