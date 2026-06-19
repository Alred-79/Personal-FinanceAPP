import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from server.src.logging_context import (
    RequestContextFilter,
    request_id_var,
    user_id_var,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [req=%(request_id)s user=%(user_id)s] %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
# Attach the request-context filter to every root handler so every record gets
# request_id/user_id (the format above references them). Outside a request they
# render as "-". A filter on the handler covers records from any logger that
# propagates to root.
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RequestContextFilter())

from server.src.limiter import limiter
from server.src.settings import settings
from server.src.db.tenant import get_tenant_db
from server.src.routers.auth import router as auth_router
from server.src.routers.expenses import router as expenses_router
from server.src.routers.income import router as income_router
from server.src.routers.transactions import router as transactions_router
from server.src.routers.accounts import router as accounts_router
from server.src.routers.spend import router as spend_router
from server.src.routers.assistant import router as assistant_router
from server.src.routers.plaid import router as plaid_router
from server.src.routers.goals import router as goals_router
from server.src.routers.users import router as users_router
from server.src.routers.budgets import router as budgets_router
from server.src.routers.recurring import router as recurring_router
from server.src.routers.networth import router as networth_router
from server.src.routers.notifications import router as notifications_router
from server.src.routers.memory import router as memory_router
from server.src.routers.subscriptions import router as subscriptions_router
from server.src.routers.receipts import router as receipts_router
from server.src.routers.imports import router as imports_router
from server.src.routers.tax import router as tax_router
from server.src.routers.forecast import router as forecast_router
from server.src.routers.settings import router as settings_router
from server.src.routers.mcp_keys import router as mcp_keys_router
from server.src.routers.rules import router as rules_router
from server.src.routers.scenarios import router as scenarios_router
from server.src.routers.analytics import router as analytics_router
from server.src.routers.game import router as game_router
from server.src.routers.assisted_actions import router as assisted_actions_router
from server.src.routers.next_action import router as next_action_router

# ---------------------------------------------------------------------------
# MCP surface (ships dark by default: settings.mcp_enabled = False)
# ---------------------------------------------------------------------------

_mcp_log = logging.getLogger("mcp")
_mcp_starlette = None

if settings.mcp_enabled:
    from server.src.db.session import SessionLocal
    from server.src.mcp.server import build_mcp_starlette

    _mcp_starlette = build_mcp_starlette(db_factory=SessionLocal)
    # HARD DEPLOYMENT REQUIREMENT (shared with Steps 02/09): the MCP per-key
    # throttle, the Step 05 pre-auth IP throttle, and the slowapi limiter are
    # all module-level, in-memory, per-process singletons; the Step 09
    # scheduler is in-process too. Running >1 worker gives each process its own
    # counters (limits multiplied) and double-fires scheduled jobs. Run a SINGLE
    # worker until a shared store (Redis) + leader election exist. This is not a
    # caveat — it is a deploy precondition. (Documented in docs/v5 execution.)
    if settings.mcp_rate_limit_enabled or settings.mcp_preauth_rate_limit_enabled:
        _mcp_log.warning(
            "MCP rate limits (per-key=%s, pre-auth IP=%s) are in-memory and "
            "per-process; run a SINGLE worker or the limits are multiplied "
            "across workers.",
            settings.mcp_key_rate_limit,
            settings.mcp_preauth_ip_rate_limit,
        )
else:
    # Explains the /mcp 404 a client sees when the surface ships dark.
    _mcp_log.info(
        "MCP surface disabled (mcp_enabled=false); /mcp is not mounted. "
        "Set mcp_enabled=true to expose it."
    )


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Step 09 — the production game scheduler (APScheduler). Started here, shut
    # down on teardown. Disabled in tests (scheduler_enabled=False) so the suite
    # is deterministic. SINGLE-WORKER ONLY — an in-process scheduler starts once
    # per worker, so >1 worker double-fires month-close/rollups (idempotent but
    # doubled work). See the deploy-requirement warning block above and
    # settings.scheduler_enabled.
    from server.src.scheduler import shutdown_scheduler, start_scheduler

    _scheduler = start_scheduler()
    if _scheduler is not None:
        _mcp_log.warning(
            "Game scheduler running in-process (per-worker). Run a SINGLE "
            "uvicorn worker or month-close/rollups double-fire."
        )
    try:
        if _mcp_starlette is not None:
            async with _mcp_starlette.lifespan(_mcp_starlette):
                yield
        else:
            yield
    finally:
        shutdown_scheduler(_scheduler)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=_lifespan)
primary = APIRouter(prefix="/api")

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    # Constrain to what the SPA actually sends rather than "*". Origins are already
    # an explicit allowlist (never wildcard), so this is hardening, not a fix — but
    # "*" methods/headers alongside credentials is broader than necessary.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)


@app.middleware("http")
async def _request_context(request: Request, call_next):
    """Stamp a request_id into the logging context for the life of the request
    and echo it back as ``X-Request-ID``. ``user_id`` defaults to "-" here and is
    overwritten by the auth dependency once the request resolves to a user.

    No reset is needed: each request runs in its own task-local contextvar
    snapshot, so a set here cannot leak into another request — and skipping the
    reset keeps the id attached to logs emitted while an SSE/streaming response
    body is still being produced after this middleware returns.
    """
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    request_id_var.set(rid)
    user_id_var.set("-")
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response

# Static assets (only when client is built)
if os.path.isdir("./client/dist/assets"):
    app.mount("/assets", StaticFiles(directory="./client/dist/assets"), name="assets")

# MCP mount (outside /api, flag-gated)
if _mcp_starlette is not None:
    app.mount("/mcp", _mcp_starlette)

# ---------------------------------------------------------------------------
# RFC 9728 well-known discovery
# ---------------------------------------------------------------------------

@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource():
    """RFC 9728 resource metadata.  Advertises header-only Bearer auth."""
    return JSONResponse({
        "resource": "Finance-Tracker MCP",
        "bearer_methods_supported": ["header"],
        "mcp_enabled": settings.mcp_enabled,
    })


# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------

# auth_router runs PRE-authentication (login/signup/refresh/logout) — it must NOT
# get the tenant dependency. Every other router is authenticated; bind the RLS
# tenant for each of its requests via get_tenant_db (no-op unless enable_rls +
# Postgres). The dependency also asserts auth, so an accidentally-public route on
# an authed router would fail loudly in the suite.
primary.include_router(auth_router)
# L1: the Plaid inbound-webhook endpoint is PUBLIC (Plaid calls it with no user
# session) and verifies a signature itself — register it without the tenant
# dependency, like auth_router. The GET catch-all won't shadow this POST.
from server.src.routers.plaid_webhook import router as plaid_webhook_router

primary.include_router(plaid_webhook_router)
_tenant_dep = [Depends(get_tenant_db)]
for _router in (
    plaid_router,
    transactions_router,
    expenses_router,
    income_router,
    accounts_router,
    spend_router,
    assistant_router,
    goals_router,
    users_router,
    budgets_router,
    recurring_router,
    networth_router,
    notifications_router,
    memory_router,
    subscriptions_router,
    receipts_router,
    imports_router,
    tax_router,
    forecast_router,
    settings_router,
    mcp_keys_router,
    rules_router,
    scenarios_router,
    analytics_router,
    game_router,
    assisted_actions_router,
    next_action_router,
):
    primary.include_router(_router, dependencies=_tenant_dep)
app.include_router(primary)


# ---------------------------------------------------------------------------
# Misc endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    # Unknown API paths are a 404, not a silent SPA fallback (which would
    # otherwise return the index.html / a null body with a 200).
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse("./client/dist/index.html")
