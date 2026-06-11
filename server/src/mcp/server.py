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
            # Don't reveal whether the key was unknown / expired / revoked.
            await _deny(
                scope, receive, send,
                message="API key rejected (unknown, expired, or revoked).",
            )
            return

        # Per-key rate limit — only after we know whose key it is.
        if settings.mcp_rate_limit_enabled and not _rate_limiter.hit(
            _rate_item, str(principal.key_id)
        ):
            await _too_many(scope, receive, send)
            return

        token = _current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_principal.reset(token)


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
    """Clear the in-memory rate-limit window (test hook only)."""
    _rate_limiter.storage.reset()


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
    """
    return mcp.http_app(
        path="/",
        transport="streamable-http",
        middleware=[Middleware(MCPAuthMiddleware, db_factory=db_factory)],
    )
