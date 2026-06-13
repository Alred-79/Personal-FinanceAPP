"""MCP server surface — streamable-HTTP transport with API-key auth.

Single responsibility: host the FastMCP instance and enforce the API-key auth
boundary at the HTTP layer.

This module is deliberately DB-free (the import guard in the test suite enforces
this).  The auth middleware receives its ``db_factory`` by dependency injection
from ``main.py``, which is the only caller that may import ``SessionLocal``.
"""

from contextvars import ContextVar
from typing import Callable

from fastmcp import FastMCP
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware import Middleware
from starlette.responses import Response

from server.src.mcp import audit
from server.src.mcp.principal import Principal
from server.src.services.mcp_key_service import MCPKeyService
from server.src.settings import settings

# ---------------------------------------------------------------------------
# Per-key rate limiting
# ---------------------------------------------------------------------------
# slowapi's @limiter.limit decorator only works on FastAPI routes, not on a
# mounted Starlette sub-app, so the MCP surface is throttled here in the one
# ASGI chokepoint instead — keyed on the resolved key_id (the "custom key_func
# on key_id" the roadmap deferred).  In-memory / per-process for v1; a shared
# store (Redis) is the later upgrade for multi-worker deployments.
_rate_item = parse(settings.mcp_key_rate_limit)
_rate_limiter = MovingWindowRateLimiter(MemoryStorage())

# ---------------------------------------------------------------------------
# Pre-auth IP rate limiting (Step 05)
# ---------------------------------------------------------------------------
# Runs at the *top* of the middleware, BEFORE any DB query, so a flood of bad
# keys is shed without costing a `resolve()` query. Keyed on the proxy-aware
# client (see ``_client_key_from_scope``) so it limits the real client behind a
# trusted proxy, not the proxy IP. Same caveat as ``_rate_limiter``:
# module-level, in-memory, per-process singleton — no cross-worker coordination,
# resets on restart (single-worker deployment invariant, shared w/ Steps 02/09).
_preauth_rate_item = parse(settings.mcp_preauth_ip_rate_limit)
_preauth_rate_limiter = MovingWindowRateLimiter(MemoryStorage())

# ---------------------------------------------------------------------------
# Principal context
# ---------------------------------------------------------------------------

_current_principal: ContextVar[Principal | None] = ContextVar(
    "mcp_principal", default=None
)


def get_principal() -> Principal:
    """Return the principal attached by MCPAuthMiddleware for this request.

    Tools call this to identify the requesting user and their scopes.
    Raises RuntimeError if called outside an authenticated MCP request.
    """
    p = _current_principal.get()
    if p is None:
        raise RuntimeError(
            "No principal in context — MCPAuthMiddleware did not run or was bypassed."
        )
    return p


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

class MCPAuthMiddleware:
    """Starlette ASGI middleware that gates every /mcp request on an API key.

    Protocol:
    * Read ``Authorization: Bearer <key>`` from the request **headers only**.
      Tokens supplied in the query string are silently ignored (→ 401).
    * Resolve the raw key via ``MCPKeyService.resolve``.
    * On success — store the ``Principal`` in ``_current_principal`` and hand
      off to the next layer.
    * On failure — respond immediately with 401 + ``WWW-Authenticate``.
    """

    def __init__(self, app, db_factory: Callable | None = None):
        self.app = app
        self._db_factory = db_factory  # injected; never imported here

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # --- Pre-auth IP throttle (Step 05) -------------------------------
        # Shed a flood of bad keys BEFORE any DB hit. Keyed on the proxy-aware
        # client so it limits the real client behind a trusted proxy. This runs
        # ahead of `self._db_factory()` / `resolve` deliberately: an invalid or
        # flooding key must not cost a query.
        if settings.mcp_preauth_rate_limit_enabled:
            client_key = _client_key_from_scope(scope)
            if not _preauth_rate_limiter.hit(_preauth_rate_item, client_key):
                audit.record_failure(reason="ip_rate_limited", client=client_key)
                await _too_many(scope, receive, send)
                return

        headers = dict(scope.get("headers", []))
        auth_bytes = headers.get(b"authorization", b"")
        auth = auth_bytes.decode("latin-1")

        if not auth.lower().startswith("bearer "):
            # A token in the query string is silently ignored for security
            # (it would leak into logs/proxies). Tell the caller to use the
            # header so a misplaced token isn't mistaken for "no credentials".
            if _has_query_token(scope):
                await _deny(
                    scope, receive, send,
                    message="Supply the API key in the 'Authorization: Bearer "
                    "<key>' header, not the query string.",
                )
            else:
                await _deny(
                    scope, receive, send,
                    message="Missing or malformed 'Authorization: Bearer <key>' header.",
                )
            return

        raw_key = auth[7:]  # strip "Bearer "

        if self._db_factory is None:
            await Response("Service unavailable", status_code=503)(scope, receive, send)
            return

        db = self._db_factory()
        try:
            principal = MCPKeyService.resolve(db, raw_key)
            db.commit()
        finally:
            db.close()

        if principal is None:
            # Don't reveal whether the key was unknown / expired / revoked /
            # disabled — the deny message stays opaque to a probing caller. The
            # audit row records the real reason for the owner. `resolve` folds
            # "disabled owner" into None too (so it can't be distinguished from
            # the outside); we audit it as `unknown_key` here because the
            # middleware can't tell the cases apart without re-querying, and the
            # opaque-from-outside contract is what matters. (The disabled case
            # is independently covered by the resolve() change + its own test.)
            audit.record_failure(reason="unknown_key")
            await _deny(
                scope, receive, send,
                message="API key rejected (unknown, expired, or revoked).",
            )
            return

        # Per-key rate limit — only after we know whose key it is.
        if settings.mcp_rate_limit_enabled and not _rate_limiter.hit(
            _rate_item, str(principal.key_id)
        ):
            audit.record_failure(
                reason="rate_limited",
                key_id=principal.key_id,
                user_id=principal.user_id,
            )
            await _too_many(scope, receive, send)
            return

        # Bind the re-authenticated principal both in the ContextVar (used by
        # the tools) AND on the ASGI scope (defense-in-depth for the SDK's
        # session-owner check). With stateless_http the SDK no longer freezes a
        # session principal at session creation, so this scope["user"] reflects
        # the principal we just re-resolved for *this* request.
        scope["user"] = principal
        token = _current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_principal.reset(token)


def _client_key_from_scope(scope) -> str:
    """Resolve the proxy-aware rate-limit key from a raw ASGI scope.

    Mirrors ``server.src.limiter._client_key`` but operates on the ASGI scope
    (the MCP middleware sees a scope, not a FastAPI ``Request``): honor the
    left-most ``X-Forwarded-For`` hop then ``X-Real-IP`` ONLY when
    ``settings.trust_proxy`` is set, otherwise fall back to the direct peer
    (``scope["client"]``). Malformed/empty headers fall through gracefully —
    never raises — and a missing ``client`` (e.g. a hand-built test scope)
    degrades to ``"unknown"`` so all such requests share one bucket.
    """
    headers = dict(scope.get("headers", []))
    if settings.trust_proxy:
        fwd = headers.get(b"x-forwarded-for", b"").decode("latin-1")
        if fwd:
            first = fwd.split(",")[0].strip()
            if first:
                return first
        real = headers.get(b"x-real-ip", b"").decode("latin-1").strip()
        if real:
            return real
    client = scope.get("client")
    if client and client[0]:
        return str(client[0])
    return "unknown"


# Query params that callers commonly (and mistakenly) use to pass a token.
_QUERY_TOKEN_KEYS = (b"token", b"access_token", b"api_key", b"apikey", b"key", b"bearer")


def _has_query_token(scope) -> bool:
    """True if the request carries a token-like param in the query string."""
    qs = scope.get("query_string", b"")
    if not qs:
        return False
    lowered = qs.lower()
    return any(key + b"=" in b"&" + lowered for key in _QUERY_TOKEN_KEYS)


async def _deny(scope, receive, send, message: str = "Unauthorized") -> None:
    response = Response(
        message,
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="Finance-Tracker MCP"'},
    )
    await response(scope, receive, send)


async def _too_many(scope, receive, send) -> None:
    response = Response(
        "Too Many Requests",
        status_code=429,
        headers={"Retry-After": "60"},
    )
    await response(scope, receive, send)


def reset_rate_limiter() -> None:
    """Clear the in-memory per-key rate-limit window (test hook only)."""
    _rate_limiter.storage.reset()


def reset_preauth_throttle() -> None:
    """Clear the in-memory pre-auth IP throttle window (test hook only)."""
    _preauth_rate_limiter.storage.reset()


# ---------------------------------------------------------------------------
# FastMCP application
# ---------------------------------------------------------------------------

mcp = FastMCP("Finance-Tracker")

# Register tools (side-effect import — must come after `mcp` is assigned)
import server.src.mcp.tools as _tools  # noqa: E402, F401


def build_mcp_starlette(db_factory: Callable | None = None):
    """Return a Starlette ASGI app wrapping the FastMCP server.

    ``db_factory`` is passed to ``MCPAuthMiddleware`` so this module never
    imports ``SessionLocal`` directly (the import guard enforces this).

    ``stateless_http=True`` (verified supported on the installed fastmcp 3.4.2 —
    ``FastMCP.http_app`` exposes the kwarg) matches the per-request auth the
    middleware already performs: the SDK no longer dispatches tool calls under a
    session principal frozen at session creation, so a disabled/revoked owner
    loses access on the very next request with no cached session keeping them
    alive. This is the transport half of C2; the ``scope["user"]`` binding in
    the middleware is the half that lands regardless of this flag.
    """
    return mcp.http_app(
        path="/",
        transport="streamable-http",
        stateless_http=True,
        middleware=[Middleware(MCPAuthMiddleware, db_factory=db_factory)],
    )
