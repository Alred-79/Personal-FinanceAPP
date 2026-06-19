"""W8 — the unified "one thing today" next-action surface.

``GET /next-action/`` returns EXACTLY ONE recommended action (or the calm
"you're all set" state) ranked deterministically across bridges, rule proposals,
challenges, streak recovery and auditor findings — see
:mod:`server.src.services.next_action`.

RLS (guardrail B1): this router is mounted with the ``get_tenant_db``
router-level dependency in ``main.py`` (like every authed router), which binds the
Postgres RLS tenant for the request transaction before the body runs. We take the
request session via ``get_db`` (the exact same session ``get_tenant_db`` bound) so
the read is tenant-scoped.

Ship-dark (B4): the endpoint ALWAYS works, regardless of ``neurodivergent_mode``.
Only the client's *defaulting* to this single-action surface is flag-gated — the
flag is surfaced to the client via ``GET /settings/`` (``features``), not here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services import next_action as next_action_service
from server.src.services.auth_service import AuthService

router = APIRouter(prefix="/next-action", tags=["next-action"])


@router.get("/")
def get_next_action(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """The single ranked next action for the current user (or the all-set state)."""
    return next_action_service.compute(db, current_user.id)
