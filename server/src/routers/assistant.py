from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, List, Annotated
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..services.assistant_service import (
    AssistantService,
    ActionService,
    ActionError,
    PlaidAccountError,
    _MEMORY_MUTATING_ACTIONS,
)
from ..services.speech_service import (
    ALLOWED_CONTENT_TYPES,
    MAX_AUDIO_BYTES,
    TTS_MEDIA_TYPE,
    SpeechService,
    TtsService,
)
from server.src.db.session import get_db
from server.src.models import (
    UserInDB,
    AssistantActionRequest,
    AssistantActionProposal,
    AssistantActionConfirm,
)
from server.src.services.auth_service import AuthService
from server.src.services import llm_budget, token_meter
from server.src.limiter import limiter
from server.src.settings import settings
from server.src.db.models import Goal as GoalORM
from server.src.money import cents_to_dollars

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
    # Pre-flight: reserve 1 request AND a conservative cost estimate. Both are
    # hard caps; the generator reconciles the cost to the actual figure (Groq
    # usage or tiktoken) and refunds/tops-up the difference once the stream ends.
    est_cost = token_meter.estimate_cost_cents(message)
    try:
        llm_budget.check_and_reserve(
            db,
            current_user.id,
            requests=1,
            est_tokens=max(1, len(message) // 4),
            est_cost_cents=est_cost,
        )
    except llm_budget.BudgetExceeded:
        raise HTTPException(
            status_code=429,
            detail="Daily AI limit reached. Please try again tomorrow.",
        )

    return StreamingResponse(
        assistant_service.chat(current_user, message, reserved_cost_cents=est_cost),
        media_type="text/event-stream",
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
# Voice input (speech-to-text)
# ---------------------------------------------------------------------------
# Turns an uploaded mic clip into text that pre-fills the chat box for the user
# to review before sending. Validation mirrors /receipts/scan/ exactly (auth +
# content-type + size, bytes held in memory only, never persisted). Transcription
# is a PAID Groq Whisper call, so it reserves one ``llm_budget`` unit (E3 —
# previously it relied on its rate limit alone, leaving STT cost uncounted). Same
# Step-02 callable-limit gotcha as /chat/ (slowapi freezes a bare string at decoration).
@router.post("/transcribe/")
@limiter.limit(lambda: settings.assistant_stt_rate_limit)
async def transcribe(
    request: Request,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content_type = (file.content_type or "").lower()
    # Some browsers append codec params, e.g. "audio/webm;codecs=opus".
    base_type = content_type.split(";", 1)[0].strip()
    if base_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Record audio (webm, mp4, wav, or mp3).",
        )

    # Reject oversize uploads using the declared size before buffering anything.
    if file.size is not None and file.size > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio too large. Maximum clip size is 25 MB.",
        )

    # Read at most one byte past the limit so a lying/absent Content-Length can't
    # exhaust memory; anything larger is rejected without holding the full body.
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio too large. Maximum clip size is 25 MB.",
        )

    # E3: reserve one budget unit before the paid Whisper call; refund on failure.
    try:
        llm_budget.check_and_reserve(db, current_user.id, requests=1)
    except llm_budget.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    try:
        text = SpeechService().transcribe(data, base_type)
    except Exception:
        # STT/network errors must never leak internals; fail gracefully so the
        # user falls back to typing.
        llm_budget.release_request(db, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not transcribe the audio. Please type your message.",
        )

    return {"text": text}


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

    # Only a memory-mutating confirm (e.g. a recategorize, which writes a
    # category preference) need evict the cached executor so the next turn
    # rebuilds its prompt with the new fact. Confirming anything else (adding a
    # transaction, a goal, a rule) must NOT evict — that would wipe the live
    # conversation buffer mid-chat for no reason. (Pillar 1A; review fix #4.)
    if claims["action"] in _MEMORY_MUTATING_ACTIONS:
        assistant_service.invalidate_agent(current_user.id)

    return {"status": "confirmed", "action": claims["action"], "result": result}


# ---------------------------------------------------------------------------
# Contextual suggestions (the Clerk's section-aware starters)
# ---------------------------------------------------------------------------
# Data-aware starter prompts for the Clerk's ticket on the section the user is
# viewing. HEURISTIC ONLY — built from the user's own rows, no LLM call — so it
# never touches the daily cost budget. OFF by default (ship-dark): a clean 404
# when the flag is off lets the client keep its static, offline fallback. This
# layer only ENRICHES; an empty list for a section means "use the static one".
class AssistantSuggestion(BaseModel):
    label: str
    prompt: str


def _data_aware_suggestions(
    db: Session, user_id: int, context: str
) -> List[AssistantSuggestion]:
    path = context or "/"
    out: List[AssistantSuggestion] = []

    if path.startswith("/goals"):
        goals = (
            db.execute(select(GoalORM).where(GoalORM.user_id == user_id))
            .scalars()
            .all()
        )
        incomplete = [g for g in goals if not g.completed and (g.amount or 0) > 0]
        if incomplete:
            # The goal closest to done — most motivating to nudge on.
            nearest = min(
                incomplete,
                key=lambda g: max(0, (g.amount or 0) - (g.progress or 0)),
            )
            remaining = cents_to_dollars(
                max(0, (nearest.amount or 0) - (nearest.progress or 0))
            )
            out.append(
                AssistantSuggestion(
                    label=f"You're ${remaining:,.0f} from ‘{nearest.name}’ — want a plan to finish it?",
                    prompt=f"Help me make a plan to finish my ‘{nearest.name}’ goal.",
                )
            )

    return out


@router.get("/suggestions/")
def get_suggestions(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    context: str = "/",
    db: Session = Depends(get_db),
) -> List[AssistantSuggestion]:
    """Data-aware contextual starters for the current section's Clerk ticket.

    Heuristic only (no LLM, no cost-budget touch). OFF by default — a 404 when
    the flag is off so the client cleanly keeps its static fallback. Returns an
    empty list for sections without a data-aware angle (again: fall back).
    """
    if not settings.assistant_suggestions_enabled:
        raise HTTPException(status_code=404, detail="Suggestions are not enabled.")
    return _data_aware_suggestions(db, current_user.id, context)


# ---------------------------------------------------------------------------
# Voice output (text-to-speech) — the Clerk reading a reply aloud
# ---------------------------------------------------------------------------
# Synthesises a reply the user ALREADY received as text (the transcript is always
# shown; this is never audio-only). PAID Groq PlayAI TTS, so it reserves one
# ``llm_budget`` unit like /transcribe/ and refunds on failure. OFF by default
# (404 when the flag is off). Same Step-02 callable-limit gotcha as /chat/.
class SpeakRequest(BaseModel):
    text: str


@router.post("/speak/")
@limiter.limit(lambda: settings.assistant_tts_rate_limit)
def speak(
    request: Request,
    payload: SpeakRequest,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    if not settings.assistant_tts_enabled:
        raise HTTPException(status_code=404, detail="Spoken replies are not enabled.")

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to speak.")

    # Reserve one budget unit before the paid call; refund on any failure.
    try:
        llm_budget.check_and_reserve(db, current_user.id, requests=1)
    except llm_budget.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    try:
        audio = TtsService().synthesize(text)
    except Exception:
        llm_budget.release_request(db, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate audio. The reply is still shown as text.",
        )

    if not audio:
        llm_budget.release_request(db, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate audio. The reply is still shown as text.",
        )

    return Response(content=audio, media_type=TTS_MEDIA_TYPE)
