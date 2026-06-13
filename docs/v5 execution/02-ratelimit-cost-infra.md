# Step 02 — Rate-limit & cost-control infrastructure

## Goal
Build the shared rate-limit + LLM-cost infrastructure that Steps 03–04 depend on, and fix the
deployment-blind limiter key first. Per the report: fix the proxy-blind `request.client.host`
keying "first or none of it works in deployment."

## Why it matters (user impact)
- **Denial of wallet (OWASP LLM10):** the assistant calls paid Groq + Tavily. Without a per-user
  daily budget, a single runaway loop or an over-eager user can run up a real bill. The owner of a
  personal-finance app is exactly the person who cares about a surprise API charge.
- **Behind a proxy** (the realistic deployment: nginx/Caddy/Cloud), every request shares the proxy
  IP. A limiter keyed on `request.client.host` then sees *all* traffic as one client — so it either
  throttles the whole app at once or (with per-route limits) is trivially defeated. Fixing the key
  is what makes every later limit real instead of cosmetic.
- A reusable budget primitive means Steps 03 (chat) and 04 (propose/confirm) don't each reinvent
  cost control inconsistently.

## Findings closed (with evidence)
- **"limiter keys on `request.client.host`"**: `server/src/limiter.py:13-16` uses
  `key_func=get_remote_address` (slowapi's `get_remote_address` reads `request.client.host`).
- **"/signup/ has no rate limit"**: `server/src/routers/auth.py::signup` has no `@limiter.limit`.
- **Foundation for C4** (Step 03): no per-user token/spend budget exists anywhere.
- **Config naming mismatch + slowapi gotcha (the important one):** `conftest.py:14` sets env
  `limiter_enabled=false`, but the settings field is `rate_limit_enabled` (`settings.py:33`). So the
  test "disable" is a **no-op typo** — the limiter is accidentally `enabled=True` for the whole
  suite. **Do NOT just rename the env var to `rate_limit_enabled=false`** — that would silently
  disable the limiter and make every rate-limit test (this step's `test_signup_rate_limited`, Step
  03's `test_chat_rate_limited`, Step 04's `test_propose_rate_limited`, and the MCP-style flow)
  false-green. The reason: slowapi captures `enabled` **at `Limiter(...)` construction time**
  (`self.enabled = enabled`, then overridden only from app config at init) and at request time
  checks `self.enabled` on the instance — it **never** re-reads the `settings` singleton
  (verified: `slowapi/extension.py` sets `self.enabled` at construction ~L164 and checks it at
  ~L568; `monkeypatch.setattr(settings, "rate_limit_enabled", True)` does not reach it). Contrast
  the MCP throttle, which **does** read `settings.mcp_rate_limit_enabled` per request
  (`mcp/server.py:127`) — that's why `test_mcp_failure_modes.py:563` can monkeypatch the setting and
  it works. slowapi can't be toggled that way.

## Preconditions
- `slowapi` Limiter is shared via `server/src/limiter.py` and registered in `main.py`.
- Existing `@limiter.limit(settings.login_rate_limit)` / `refresh_rate_limit` must keep working —
  do not rename the `limiter` object.

## Implementation
1. **Proxy-aware key function** (`server/src/limiter.py`):
   ```python
   def _client_key(request: Request) -> str:
       if settings.trust_proxy:
           fwd = request.headers.get("x-forwarded-for")
           if fwd:
               return fwd.split(",")[0].strip()   # left-most = original client
           real = request.headers.get("x-real-ip")
           if real:
               return real.strip()
       return get_remote_address(request)

   limiter = Limiter(key_func=_client_key, enabled=settings.rate_limit_enabled)
   ```
   When `trust_proxy=False`, forwarded headers are **ignored** (otherwise any client spoofs them to
   evade limits). Document that `trust_proxy=True` is only safe when a trusted proxy *sets* the
   header.
2. **Settings** (`server/src/settings.py`), in the rate-limit block:
   ```python
   trust_proxy: bool = False
   signup_rate_limit: str = "5/hour"
   assistant_rate_limit: str = "20/hour"
   # LLM cost ceiling (denial-of-wallet). The HARD cap is requests/day — it needs no
   # post-stream token count, so it actually enforces on the streaming path.
   llm_daily_request_budget: int = 100
   # Token budget is ADVISORY/observability only until a real streaming token source is
   # wired (see Step 03). Do not present it to the user as a hard cap while it meters 0.
   llm_daily_token_budget: int = 200_000
   assistant_max_iterations: int = 8
   assistant_max_execution_seconds: int = 60
   ```
3. **Signup limit** (`auth.py::signup`): add `@limiter.limit(settings.signup_rate_limit)` and the
   `request: Request` param (slowapi needs it). Order with the Step 01 guard so the count-guard
   still runs.
3a. **A real test toggle for the limiter** (the crux — see Findings). Because slowapi's `enabled`
   is fixed at construction, provide a fixture in `server/tests/conftest.py` that flips the
   **instance** attribute, not the setting:
   ```python
   @pytest.fixture
   def rate_limited(monkeypatch):
       """Turn the shared slowapi limiter ON for a test and reset its window."""
       from server.src.limiter import limiter
       monkeypatch.setattr(limiter, "enabled", True)
       limiter.reset()            # clear any prior counts; slowapi Limiter has reset()
       yield limiter
       limiter.reset()
   ```
   And make the **default** test state genuinely off by setting `limiter.enabled = False` once in
   conftest import (or a session autouse fixture), replacing the broken `limiter_enabled=false` env
   line. Tests that assert a 429 depend on `rate_limited`; all other tests run with the limiter off
   and deterministic. (If the installed slowapi `Limiter` lacks `.reset()`, clear
   `limiter._limiter` / its storage as `reset_rate_limiter()` does for the MCP throttle — verify the
   method name against the installed version.)
4. **LLM budget module** (`server/src/services/llm_budget.py`), DB-backed, race-safe.

   **⚠ Token counts are NOT available on the streaming path — decide the budget unit first.** The
   chat path streams via `executor.astream_events(version="v2")` (`assistant_service.py:1056`),
   which does **not** surface usage metadata the way `.invoke()` does — there is no `tokens_used`
   value to record after a stream (verified). Step 03's reconciliation snippet assumes one exists; it
   doesn't. So this primitive must be **dual-unit and honest about what it actually meters**:
   - **Primary, always-correct unit = `requests`.** Every chat/propose call costs 1 request. This is
     the cap that genuinely protects against denial-of-wallet on the streaming path, because it needs
     no post-hoc token count. Make `settings.llm_daily_request_budget: int` the real ceiling.
   - **Tokens = best-effort estimate, not a hard guarantee.** Keep a `tokens` column for
     observability and a *pre-flight* estimate (e.g. `len(prompt)//4 + ceil`), but treat the token
     ceiling as advisory unless/until a real usage source is wired (see Step 03's "token source"
     note for the options: char-estimate, a LangChain usage callback that *does* fire on streaming in
     the installed version, or switching the model call to capture `usage_metadata`). Do **not**
     ship a "200k tokens/day" cap whose enforcement is silently `record_actual(..., 0)` — that reads
     to the user as a working cap while metering nothing.
   - New ORM table `LlmUsage(user_id, day TEXT, tokens INT, requests INT)`, PK `(user_id, day)`.
     Add to `server/src/db/models.py` (so `Base.metadata.create_all` picks it up in tests).
   - `class BudgetExceeded(Exception)`.
   - `def today_key() -> str`: one canonical server-local date string (note the report's
     server-local-date caveat; use a single helper so chat + actions agree on the day boundary).
   - `def check_and_reserve(db, user_id, *, est_tokens=0, requests=1) -> None`: atomically add
     `requests` (and `est_tokens` for observability) via one SQL UPDATE that runs inside the request
     transaction. Use a **conditional UPDATE** so the cap check and the increment are a single
     statement (no read-then-write window):
     ```sql
     -- ensure the row exists, then:
     UPDATE llm_usage SET requests = requests + :req, tokens = tokens + :est
       WHERE user_id = :uid AND day = :day AND requests + :req <= :request_budget
     ```
     `rowcount == 0` (after confirming the row exists) → over cap → raise `BudgetExceeded`. This is
     the same TOCTOU-free pattern Step 06 uses for transfers; it does **not** depend on "increment
     then roll back," which is racy under read-then-compare. Seed the row first with
     `INSERT … ON CONFLICT(user_id,day) DO NOTHING`.
   - `def record_actual(db, user_id, tokens) -> None`: reconcile the *token* estimate after a run if
     and only if a real token count is available; a no-op when it isn't (the request was already
     counted at reserve time, so the cap is intact regardless). Never go negative.
   - `def remaining(db, user_id) -> int`: requests remaining today, for surfacing "you're near your
     daily AI limit" to the UI.

## Tests to add (`server/tests/test_hardening.py`)
- `test_limiter_key_uses_forwarded_when_trusted`: monkeypatch `settings.trust_proxy=True`; build a
  fake `Request` with `x-forwarded-for: "1.2.3.4, 10.0.0.1"`; assert `_client_key` → `"1.2.3.4"`.
- `test_limiter_key_ignores_forwarded_when_untrusted`: `trust_proxy=False` + spoofed header →
  falls back to `request.client.host` (assert it does **not** return the spoofed value).
- `test_budget_blocks_over_cap`: with a tiny `llm_daily_request_budget` (e.g. 1), two
  `check_and_reserve(requests=1)` calls — second raises `BudgetExceeded`; assert the over-cap
  reservation did **not** persist (`requests` stayed at 1, not 2).
- `test_budget_resets_next_day`: reserve to the cap for `day=D`; with `today_key` monkeypatched to
  `D+1`, a reservation succeeds (fresh row).
- `test_budget_atomic_increment_no_lost_update`: N sequential `check_and_reserve(requests=1, est=K)`
  calls leave `requests=N` and `tokens=N*K` in the row (proves the increment is an issued SQL
  UPDATE, not a read-modify-write on a stale Python value). **Do not call this a concurrency test —
  sequential calls cannot surface a lost update; they only prove the arithmetic.** The real
  concurrency guarantee is the *conditional UPDATE* (cap-and-increment in one statement) plus
  SQLite's single-writer serialization; assert that property structurally (the WHERE clause carries
  the cap) rather than claiming a sequential test proves it. If genuine parallelism is wanted, stage
  it against a **file-backed** SQLite DB with real threads — the in-memory StaticPool single
  connection used by the suite cannot interleave writers.
- `test_signup_rate_limited`: use the `rate_limited` fixture (NOT `monkeypatch.setattr(settings,
  ...)`), set `signup_rate_limit="1/minute"` via `monkeypatch.setattr(settings, ...)` **and**
  re-decorate is not needed (the decorator reads the string at call time via the limiter), second
  signup attempt from the same key → 429. (Coordinate with Step 01: the 2nd signup is also blocked
  by the single-user guard — use distinct fixtures, or assert "429 *or* 409 but never 200". If the
  limit string is captured at decoration time in this slowapi version, set `signup_rate_limit`
  **before** the app imports — verify and adjust.)

## User-centric & edge-case checks
- `X-Forwarded-For` with multiple hops → take the **left-most** (original client), not the proxy.
- Empty/malformed forwarded header → graceful fallback, never a 500.
- Budget rollover at local midnight must be deterministic (single `today_key`) so a user isn't
  blocked at 23:59 then mysteriously unblocked at 00:01 by a *different* date function elsewhere.
- A failed LLM call before any work starts must **not** consume budget. Because the unit is
  *requests* reserved at the endpoint, Step 03 must reconcile the reserved request back down (or
  reserve only after the stream actually starts) so a request that 500s before any model call doesn't
  permanently burn a slot. `record_actual(..., 0)` is a no-op for the request count by design.
- Surface `remaining()` (requests left today) so the UI can warn before the hard cap — denying with
  no explanation reads as a bug to the user. Do **not** surface a token "remaining" number derived
  from a meter that records 0 on streaming — it would always read full and mislead.

## Regression guardrails
- Existing login/refresh/receipt limits unchanged (same `limiter` object, same decorators).
- **Critical:** the limiter is accidentally ON in the current suite (the `limiter_enabled` typo).
  Flipping it OFF by default (via the new `rate_limited` opt-in fixture) may surface tests that
  *implicitly* relied on it being on. After wiring the fixture, run the **whole** suite and
  reconcile any test that was leaning on the accidental-on behavior — don't just green the new ones.
  Pay attention to `test_auth.py` (repeated login/refresh) and any MCP-key flow.
- Toggle via `limiter.enabled` (instance attr), never via `settings.rate_limit_enabled` at runtime —
  the latter does nothing once the Limiter is built.
- `Base.metadata.create_all` must create `llm_usage` in the in-memory test DB (import the model in
  `db/models.py` and ensure it's registered).

## Done-when
- [ ] Proxy-aware key honors forwarded headers only when `trust_proxy`; ignores spoofs otherwise.
- [ ] New settings exist; signup is rate-limited.
- [ ] `llm_budget` enforces a **request/day** hard cap via a conditional UPDATE (no read-then-write),
      resets daily; `BudgetExceeded` + `remaining` available. Token figure is advisory-only and not
      presented as a hard cap.
- [ ] conftest env-var mismatch fixed; new tests green; full suite green.
