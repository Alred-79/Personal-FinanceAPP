from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Dict, List, Annotated
from sqlalchemy.orm import Session

from ..services.assistant_service import AssistantService, ActionService, ActionError
from server.src.db.session import get_db
from server.src.models import (
    UserInDB,
    AssistantActionRequest,
    AssistantActionProposal,
    AssistantActionConfirm,
)
from server.src.services.auth_service import AuthService

router = APIRouter(prefix="/assistant", tags=["assistant"])
assistant_service = AssistantService()


@router.post("/chat/")
async def chat(
    message: str,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
):
    """
    Chat endpoint that streams the response
    """
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
@router.post("/actions/propose/")
def propose_action(
    payload: AssistantActionRequest,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
) -> AssistantActionProposal:
    """Validate a proposed write action and return a confirmation token.

    Nothing is written here. The change is committed only when the returned
    token is sent back to ``/assistant/actions/confirm/``.
    """
    try:
        norm, summary = ActionService.validate(payload.action, payload.params)
    except ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = ActionService.make_token(current_user.id, payload.action, norm)
    return AssistantActionProposal(
        action=payload.action, params=norm, summary=summary, token=token
    )


@router.post("/actions/confirm/")
def confirm_action(
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
    except ActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "confirmed", "action": claims["action"], "result": result}
