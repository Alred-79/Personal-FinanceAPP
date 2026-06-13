from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Dict, List, Annotated
from sqlalchemy.orm import Session

from ..services.assistant_service import (
    AssistantService,
    ActionService,
    ActionError,
    PlaidAccountError,
)
from server.src.db.session import get_db
from server.src.models import (
    UserInDB,
    AssistantActionRequest,
    AssistantActionProposal,
    AssistantActionConfirm,
)
from server.src.services.auth_service import AuthService
from server.src.services import llm_budget
from server.src.limiter import limiter
from server.src.settings import settings

router = APIRouter(prefix="/assistant", tags=["assistant"])
assistant_service = AssistantService()


# NOTE (Step 02 gotcha): slowapi captures a plain limit STRING at decoration
# time and never re-reads it. We pass a CALLABLE instead, which slowapi
# evaluates per-request, so the limit honors ``settings.assistant_rate_limit``
# live (and a test can tighten it). The limiter's ``enabled`` flag is STILL
# frozen at construction — tests flip ``limiter.enabled`` (the instance), never
# ``settings.rate_limit_enabled``.
@router.post("/chat/")
@limiter.limit(lambda: settings.assistant_rate_limit)
async def chat(
    request: Request,
    message: str,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Chat endpoint that streams the response (C4 denial-of-wallet caps).

    Two ceilings guard the single most expensive surface in the app:

    * **Rate limit** (``@limiter.limit``): trips at the endpoint, *before* the
      stream starts, so a looping tab or buggy retry can't open many SSE
      streams. A 429 here means "too many requests, try again in a minute".
    * **Daily request budget** (pre-flight ``check_and_reserve``): reserves one
      request — the genuinely-enforced hard cap (the streaming path exposes no
      token count to meter; see ``llm_budget``). Reserving here, on the request
      ``db`` while it is still open, means an over-budget user gets a clean 429
      *before* any Groq/Tavily call — never a half-open stream that errors
      mid-flight. A 429 here means "daily AI limit reached, try tomorrow".

    The reservation is reconciled inside the generator's OWN session: this
    endpoint's ``db`` is closed by FastAPI once it returns the StreamingResponse,
    so the generator can't borrow it (see ``AssistantService.chat``). If the
    stream fails before any model call, the reserved request is released so a
    failure doesn't permanently burn a daily slot.
    """
    try:
        llm_budget.check_and_reserve(
            db,
            current_user.id,
            requests=1,
            # Advisory only (not a cap): a rough pre-flight token estimate so the
            # observability figure isn't permanently 0. ~4 chars/token heuristic.
            est_tokens=max(1, len(message) // 4),
        )
    except llm_budget.BudgetExceeded:
        raise HTTPException(
            status_code=429,
            detail="Daily AI limit reached. Please try again tomorrow.",
        )

    return StreamingResponse(
        assistant_service.chat(current_user, message), media_type="text/event-stream"
    )


@router.get("/history/")
async def get_history(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ]
) -> List[Dict[str, str]]:
    """
    Get chat history
    """
    return assistant_service.get_chat_history(current_user)


@router.post("/clear/")
async def clear_history(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ]
):
    """
    Clear chat history
    """
    assistant_service.clear_history(current_user)
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Write actions that need a confirmation step
# ---------------------------------------------------------------------------
# Rate-limit propose/confirm against abuse/cost (C5). Same Step 02 gotcha as
# /chat/: pass a CALLABLE so the limit honors ``settings.assistant_rate_limit``
# live per request; the limiter's frozen ``enabled`` flag is flipped by tests via
# ``limiter.enabled`` (the instance), never the setting. (Confirm is also
# replay-guarded by ``reserve_jti`` — the rate limit is about abuse/cost, not
# correctness.)
@router.post("/actions/propose/")
@limiter.limit(lambda: settings.assistant_rate_limit)
def propose_action(
    request: Request,
    payload: AssistantActionRequest,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
) -> AssistantActionProposal:
    """Validate a proposed write action and return a confirmation token.

    Nothing is written here. The change is committed only when the returned
    token is sent back to ``/assistant/actions/confirm/``.
    """
    try:
        norm, summary = ActionService.validate(payload.action, payload.params)
        # Surface the Plaid double-count refusal at propose time so the user is
        # told before they ever see an Approve button (rather than only at
        # confirm). ``execute`` re-checks as the backstop.
        ActionService.guard_account(db, current_user.id, payload.action, norm)
    except PlaidAccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = ActionService.make_token(current_user.id, payload.action, norm)
    return AssistantActionProposal(
        action=payload.action, params=norm, summary=summary, token=token
    )


@router.post("/actions/confirm/")
@limiter.limit(lambda: settings.assistant_rate_limit)
def confirm_action(
    request: Request,
    payload: AssistantActionConfirm,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Execute a previously proposed action, given its confirmation token."""
    try:
        claims = ActionService.decode_token(payload.token)
    except ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # The token is bound to the user who proposed the change.
    if int(claims.get("uid", -1)) != int(current_user.id):
        raise HTTPException(
            status_code=403, detail="This confirmation does not belong to you."
        )

    # Use it once: claim the token before running the action so a replay (a double
    # click or a retry) can't commit the same change twice. The claim shares this
    # request's transaction with the write below, so if the action fails and rolls
    # back, the token claim rolls back too and stays reusable.
    if not ActionService.reserve_jti(db, current_user.id, claims.get("jti")):
        raise HTTPException(
            status_code=409, detail="This action has already been confirmed."
        )

    try:
        result = ActionService.execute(
            db, current_user.id, claims["action"], claims["params"]
        )
    except PlaidAccountError as exc:
        # Account got Plaid-linked between propose and confirm: refuse with 422
        # (and the human explanation) rather than a generic 400.
        raise HTTPException(status_code=422, detail=str(exc))
    except ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "confirmed", "action": claims["action"], "result": result}
