"""WS2 request-lifecycle tenant binding.

``get_tenant_db`` is a FastAPI dependency that resolves the request's session
(via ``get_db``) AND the authenticated user (via ``get_current_active_user``),
then binds the Postgres RLS tenant GUC for the request's transaction. Because
FastAPI resolves ``get_db`` once per request and caches it, the session bound
here is the exact one the route body and the auth dependency use — and
``set_tenant`` runs AFTER auth resolves, INSIDE the open transaction (``SET
LOCAL`` semantics → cannot leak across pooled connections).

Applied as a router-level dependency on every authenticated router (see
main.py). The unauthenticated auth router is deliberately excluded. No-op unless
``settings.enable_rls`` and the dialect is Postgres (``set_tenant`` self-guards).
"""
import re

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from server.src.settings import settings

from ..services.auth_service import AuthService, is_demo_user
from .rls import set_tenant
from .session import get_db


_DEMO_READ_ONLY_DETAIL = {
    "code": "demo_read_only",
    "message": (
        "Sample data is read-only. Decision and rule previews still work; "
        "create your own ledger to add, edit, or delete records."
    ),
}

# These POST routes are computations, not commands: each evaluates caller input
# against the canonical sample ledger without persisting a row. Keep the list
# narrow and path-exact so a new write endpoint is denied by default until it is
# explicitly reviewed as side-effect-free.
_DEMO_READ_ONLY_POST_PATHS = frozenset(
    {
        "/api/rules/preview",
        "/api/scenarios/compose-preview",
        "/api/scenarios/compare",
        "/api/scenarios/evaluate",
    }
)
_DEMO_SAVED_SCENARIO_EVALUATE = re.compile(
    r"^/api/scenarios/[1-9][0-9]*/evaluate$"
)


def _demo_post_is_read_only_preview(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return (
        normalized in _DEMO_READ_ONLY_POST_PATHS
        or _DEMO_SAVED_SCENARIO_EVALUATE.fullmatch(normalized) is not None
    )


def _enforce_shared_demo_read_only(request: Request, current_user) -> None:
    """Deny commands against the one shared, canonical demo ledger.

    The guard lives at the authenticated-router boundary, before request-body
    validation or route code, so every current and future financial CRUD route
    is covered. Demo mode must be explicitly enabled: an ordinary deployment
    and every non-demo user retain their existing behavior.
    """
    if not settings.demo_mode_enabled or not is_demo_user(current_user):
        return
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.method == "POST" and _demo_post_is_read_only_preview(request.url.path):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_DEMO_READ_ONLY_DETAIL,
    )


def get_tenant_db(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(AuthService.get_current_active_user),
) -> Session:
    _enforce_shared_demo_read_only(request, current_user)
    if settings.enable_rls:
        set_tenant(db, current_user.id)
    return db
