# v5 Execution — Bug & Quality Remediation

Sequenced, verifiable remediation of the comprehensive bug report (5 critical, ~30 high, ~40
medium findings). Validated against the source; the large majority were confirmed. Key re-triage:
**this is a single-user app**, so C1 (global game substrate) collapses from a multi-module rewrite
to enforcing the single-user invariant.

Execute **in order** — later steps depend on earlier ones. Each file ends with **Verification →
User-centric & edge-case checks → Regression guardrails → Done-when**. Do not advance until
"Done-when" passes. Run `pytest -q` (server) and `npx vitest run` (client) per step.

**Hard dependencies (not just ordering — these will break if ignored):**
- **02 → 03, 04:** the rate-limit toggle and LLM-budget primitive from 02 are reused. Note 02's
  slowapi gotcha: the limiter's `enabled` is fixed at construction, so tests must flip
  `limiter.enabled` (the instance), **never** `settings.rate_limit_enabled` at runtime.
- **03 token-source decision (decide before building):** the streaming chat path exposes **no token
  count** (`astream_events` v2). The LLM budget's hard cap is therefore **requests/day**, not tokens;
  a token cap is advisory until a real source is wired. Steps 02/03 are written around this — don't
  ship a token cap that meters 0.
- **03 → 10 (cannot be split):** Step 03 removes the `user_id` param from `/plaid/link-token/`;
  the client's `fetchLinkToken` (`store.ts:697`) still sends it. If 03 ships without 10's
  `fetchLinkToken` fix, Plaid connect breaks. Ship them together or 10 immediately after 03.
- **07 precondition (do first):** before removing `refresh_token` from response bodies, **grep
  `client/src` for `refresh_token`** and migrate any usage to the cookie — this is a precondition,
  not a nicety.
- **06 ↔ 08 (mutual, ship close together):** Step 06's transfer guard is name-keyed; Step 08
  de-name-keys Plaid and **must** update that guard. The interval between 06 (new ledger writes) and
  08 (de-name-keying) is a regression window: a **renamed** Plaid account is mis-classified as manual
  and a transfer into it double-counts on next sync. Land 06 and 08 back-to-back, not across
  releases.
- **Single-worker deployment invariant (02, 05, 09):** the slowapi limiter, the MCP per-key + new
  pre-auth throttles, and Step 09's APScheduler are all **in-process, per-worker** state. Running >1
  worker multiplies rate limits and double-fires scheduled jobs. This app must run **one worker**
  until a shared store (Redis) + leader-elected scheduler exist. Enforce at startup / document in
  deploy.
- **05 caveat:** `stateless_http` support in the installed `fastmcp` is **not verified** — Step 05
  verifies it before relying on it and degrades gracefully if absent.

| # | File | Closes |
|---|------|--------|
| 01 | [single-user invariant](01-single-user-invariant.md) | C1 (re-scoped), signup count guard |
| 02 | [rate-limit & cost infra](02-ratelimit-cost-infra.md) | proxy-aware limiter, signup limit, LLM budget primitive |
| 03 | [Plaid auth + LLM caps](03-plaid-auth-and-llm-caps.md) | **C3**, **C4** |
| 04 | [assistant action safety](04-assistant-action-safety.md) | **C5** + unwired approval loop |
| 05 | [MCP hardening](05-mcp-hardening.md) | **C2** + disabled-user / pre-auth throttle / audit |
| 06 | [money correctness](06-money-correctness.md) | balance races, transfers, pagination, rollover, allotment, S2S |
| 07 | [auth hardening](07-auth-hardening.md) | refresh-in-body, password change, game_mode |
| 08 | [Plaid integrity](08-plaid-integrity.md) | encrypt token, routing, dedup, balances, rules |
| 09 | [game-substrate integrity](09-game-substrate-integrity.md) | folds, alerts, heat, scheduler, boss ownership |
| 10 | [client correctness](10-client-correctness.md) | dates, logout, errors, dialog, Plaid, AbortController |

Out-of-scope (low-severity + large refactors + production guardrails) is listed at the end of
Step 10.
