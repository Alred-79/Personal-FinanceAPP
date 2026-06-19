"""Imports router — the Reconciliation Desk / Import Anything surface.

Turn a messy financial document (a bank-statement PDF, a screenshot, a pasted
blob) into reconciled, reviewable transactions, even when the bank isn't on
Plaid. The heavy lifting lives in ``ReconciliationService``; this router is the
thin HTTP seam plus cost/size guards.

Flow:
* ``POST /imports/extract/``        — upload a file or post text → a review payload
* ``GET  /imports/sessions/{id}/``  — re-fetch the payload (survives a reload)
* ``PATCH /imports/sessions/{id}/rows/{row_id}/`` — edit a row, re-check balance
* ``POST /imports/sessions/{id}/discard/`` — abandon without writing

The COMMIT is deliberately NOT here: it reuses the assistant's existing
propose→confirm token machinery via the ``commit_import_session`` action
(``/assistant/actions/propose/`` then ``/assistant/actions/confirm/``), so the
one-time-token replay guard and audit path are shared, not duplicated.

PII NOTE: the uploaded bytes / pasted text live only in memory for the request;
only the parsed rows persist (see ``reconciliation_service``).
"""

from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.limiter import limiter
from server.src.models import ImportRowPatchIn, ImportSessionOut, ImportTextIn, UserInDB
from server.src.services import llm_budget
from server.src.services.auth_service import AuthService
from server.src.services.detangle_service import DetangleService
from server.src.services.import_service import ImportService, TaxFormDetected
from server.src.services.reconciliation_service import ReconciliationService
from server.src.settings import settings

router = APIRouter(prefix="/imports", tags=["imports"])

# Statement documents we can hand to the vision model. CSV/plain text come in via
# the JSON text path instead, not as a file upload.
_ALLOWED_DOC_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "application/pdf",
}


@router.post("/extract/", response_model=ImportSessionOut)
@limiter.limit(settings.import_extract_rate_limit)
async def extract_document(
    request: Request,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    account_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Extract + reconcile an uploaded statement document into a review payload."""
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Upload a PNG, JPEG, WebP, or PDF.",
        )
    if file.size is not None and file.size > settings.import_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum statement size is 15 MB.",
        )
    data = await file.read(settings.import_max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.import_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum statement size is 15 MB.",
        )

    return _run_extract(
        db,
        current_user.id,
        account_id=account_id,
        raw_bytes=data,
        content_type=content_type,
    )


@router.post("/extract/text/", response_model=ImportSessionOut)
@limiter.limit(settings.import_extract_rate_limit)
def extract_text(
    request: Request,
    payload: ImportTextIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Extract + reconcile a pasted statement blob into a review payload."""
    return _run_extract(
        db,
        current_user.id,
        account_id=payload.account_id,
        raw_text=payload.text,
    )


def _run_extract(
    db: Session,
    user_id: int,
    *,
    account_id: int,
    raw_bytes: Optional[bytes] = None,
    content_type: Optional[str] = None,
    raw_text: Optional[str] = None,
) -> dict:
    """Shared extract path: budget gate → classify+ingest → review payload.

    Routes through ``ImportService`` (Import Anything), which classifies the
    document and dispatches to the right extractor (statement → reconciliation,
    feed/unknown → balance-less reconciliation, receipt → single-row session).
    """
    # Reserve budget before the paid model call(s). ImportService makes TWO paid
    # Groq calls — a classify call plus an extract call — so reserve 2 requests
    # (E3: it previously reserved 1, under-counting by half). Both are bounded by
    # this reservation and the endpoint rate limit. Refund both if ingest fails
    # before/anywhere in the paid work.
    try:
        llm_budget.check_and_reserve(db, user_id, requests=2)
    except llm_budget.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    try:
        session, detected_kind = ImportService(db).ingest_any(
            user_id=user_id,
            account_id=account_id,
            raw_bytes=raw_bytes,
            content_type=content_type,
            raw_text=raw_text,
        )
    except TaxFormDetected as exc:
        # A tax form was dropped on the statement door: redirect to the tax-doc
        # upload (stricter PII). Refund the reserved units — no rows were written.
        llm_budget.release_request(db, user_id, requests=2)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    except ValueError as exc:
        llm_budget.release_request(db, user_id, requests=2)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        # Model/network failure: give the reserved budget back and fail gracefully.
        llm_budget.release_request(db, user_id, requests=2)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read the document. Please try a clearer file or paste the text.",
        )

    payload = ReconciliationService(db).review_payload(user_id, session.id)
    payload["detected_kind"] = detected_kind
    return payload


@router.get("/sessions/{session_id}/", response_model=ImportSessionOut)
def get_session(
    session_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Re-fetch a session's review payload (the parsed rows survive a reload)."""
    try:
        return ReconciliationService(db).review_payload(current_user.id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/sessions/{session_id}/rows/{row_id}/", response_model=ImportSessionOut)
def patch_row(
    session_id: int,
    row_id: int,
    payload: ImportRowPatchIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Edit a single parsed row and get the refreshed (re-reconciled) payload."""
    try:
        return ReconciliationService(db).patch_row(
            current_user.id,
            session_id,
            row_id,
            title=payload.title,
            amount_dollars=payload.amount,
            date=payload.date,
            category=payload.category,
            included=payload.included,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/sessions/{session_id}/discard/")
def discard_session(
    session_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Abandon a session without writing any transactions."""
    try:
        ReconciliationService(db).discard_session(current_user.id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "discarded"}


@router.post("/detangle/run/")
def run_detangle(
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """On-demand Detangler pass: flag transfer/refund/duplicate pairs.

    Surfaces each as a deduplicated notification; never edits money. The same
    work also runs nightly via the scheduler. Returns how many NEW pairings were
    flagged this run (idempotent, so a repeat run reports 0).
    """
    created = DetangleService(db).run(current_user.id)
    return {"flagged": len(created)}
