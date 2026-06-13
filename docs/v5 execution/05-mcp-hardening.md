# Step 05 — C2 MCP hardening

## Goal
Close **C2** (MCP runs stateful, so per-request principal binding is effectively cosmetic) and the
MCP HIGH/MEDIUM items: disabled users keep access, auth failures/rate-limit hits aren't audited,
and the per-key throttle runs *after* a DB hit (so invalid keys still cost a query).

## Why it matters (user impact)
- MCP exposes the user's **financial data** to third-party agents via an API key. Even though this
  is a single-user app (which softens the cross-principal-confusion angle), the surface is the most
  sensitive one in the system, and the fixes are cheap and standard. The single user still wants:
  a revoked/disabled account to immediately lose MCP access; a flood of bad keys not to hammer the
  DB; and an audit trail of *failed* access attempts, not just successful ones, so they can tell if
  someone is probing their key.
- `stateless_http=True` matches the per-request auth the middleware already implements — keeping it
  stateful means the framework can dispatch tool calls under a session principal frozen at session
  creation, diverging from the re-authenticated principal. Aligning them removes a whole class of
  "which principal is this actually running as?" ambiguity.

## Findings closed (with evidence)
- **C2:** `server/src/mcp/server.py:192-196` builds `mcp.http_app(...)` with **no**
  `stateless_http=True`; `scope["user"]` is never set, so the SDK's session-owner check is inert.
- **Disabled users retain access:** `MCPKeyService.resolve` (`mcp_key_service.py:158`) and the
  middleware (`server.py:111-124`) never check `user.disabled` (grep: no `disabled` reference in
  the MCP path).
- **Throttle after DB hit:** `server.py:113-114` resolves the key (a DB query + commit) *then*
  `:127-131` applies the per-key rate limit — so an invalid/flooding key still costs a query.
- **No audit of failures:** `audit.py` records tool calls but the deny/`_too_many` paths
  (`server.py:118-131`) don't audit.

## Preconditions
- Step 02 merged (proxy-aware key for the pre-auth IP throttle).
- `stateless_http` is **confirmed supported** by `mcp.http_app()` in the installed package, so the
  core change is viable. Still re-read the `http_app` signature before editing to confirm the exact
  kwarg name/placement for this version.

## Implementation
1. **Stateless transport + scope user** (`server.py::build_mcp_starlette`): pass
   `stateless_http=True` to `mcp.http_app(...)`. In `MCPAuthMiddleware.__call__`, after resolving
   the principal, set `scope["user"] = principal` (defense-in-depth for the SDK's owner check)
   alongside the existing `_current_principal.set(principal)`.
2. **Reject disabled users:** in `MCPKeyService.resolve` (or right after it in the middleware),
   load the owning `User` and return `None` / deny when `user.disabled`. Prefer doing it in
   `resolve` so every caller benefits and the deny message stays the existing opaque
   "API key rejected (unknown, expired, or revoked)" (don't reveal "disabled" specifically).
3. **Pre-auth IP throttle:** add an IP-based throttle (reuse the Step 02 proxy-aware key) at the
   *top* of `__call__`, **before** `self._db_factory()` / `resolve`, so a flood of bad keys is
   rejected without a DB query. Keep the existing per-key throttle (`:127`) as the second layer for
   authenticated abuse. **Caveat (state parity):** like the existing `_rate_limiter`
   (`server.py`), this pre-auth throttle is a **module-level, in-memory, per-process** singleton —
   it does not coordinate across workers/hosts and resets on restart. That matches the code's
   existing posture (the per-key limiter has the same caveat) and is fine for v1, but say so
   explicitly and add a `reset()` test hook mirroring `reset_rate_limiter()` so tests are
   deterministic.
4. **Audit failures:** in `_deny` / `_too_many` call sites (`server.py:118-131`), record an audit
   row (reason: `unknown_key` | `disabled` | `rate_limited`) via `audit.py`. The current audit is
   log-only (MEDIUM finding) — at minimum log structured; persisting is a stretch (note for backlog
   if the audit store isn't DB-backed yet).

## Tests to add (`server/tests/test_mcp_*.py`)
- `test_disabled_user_denied`: a valid key whose owner is `disabled=True` → 401; assert no tool
  runs.
- `test_stateless_http_enabled`: assert `build_mcp_starlette` constructs the app with stateless
  transport (inspect the call / a flag on the returned app, or a behavioral test that two requests
  with different keys never share a principal).
- `test_preauth_throttle_skips_db`: enable the IP throttle, exceed it, and assert the DB factory /
  `resolve` is **not** called (monkeypatch `MCPKeyService.resolve` to raise if invoked) → 429.
- `test_invalid_key_audited`: a bad key produces an audit record/log with reason `unknown_key`.
- `test_rate_limit_hit_audited`: tripping the per-key throttle produces an audit record.
- Keep/adjust existing `test_mcp_failure_modes.py`, `test_mcp_policy.py`, `test_mcp_context.py`.

## User-centric & edge-case checks
- Deny messages stay **opaque** (don't leak unknown vs expired vs revoked vs disabled) so a probing
  caller learns nothing — but the *audit* records the real reason for the owner.
- The pre-auth throttle must use the proxy-aware key so it actually limits per real client behind a
  proxy, not per proxy IP.
- Disabling the account (the user "locks" themselves or revokes) takes effect on the **next**
  request, even mid-session — verify with the stateless change that no cached session keeps a
  disabled user alive.
- `Retry-After` header on 429 (already present in `_too_many`) is preserved on the pre-auth path so
  clients back off correctly.

## Regression guardrails
- The **known-flaky** MCP concurrency test is not a regression — don't chase it (memory
  persfin-v4-substrate-gotchas).
- `stateless_http` may break tests that assumed a persistent session — update those to the
  stateless request model rather than reverting the flag.
- Run the full MCP suite: `pytest -q server/tests/test_mcp_*.py` plus `test_mcp_import_guard.py`
  (the import guard must still pass — don't import `SessionLocal` directly in `server.py`).

## Done-when
- [ ] App built stateless; `scope["user"]` set per request.
- [ ] Disabled users denied; deny message stays opaque.
- [ ] Pre-auth IP throttle rejects floods without a DB hit; per-key throttle still present.
- [ ] Auth failures + rate-limit hits audited.
- [ ] MCP suite green (flaky concurrency test excepted).