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
from fastapi import Depends
from sqlalchemy.orm import Session

from server.src.settings import settings

from ..services.auth_service import AuthService
from .rls import set_tenant
from .session import get_db


def get_tenant_db(
    db: Session = Depends(get_db),
    current_user=Depends(AuthService.get_current_active_user),
) -> Session:
    if settings.enable_rls:
        set_tenant(db, current_user.id)
    return db
