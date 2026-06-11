"""Receipts router. Scans a receipt into a prefilled transaction draft.

``POST /receipts/scan/`` takes an uploaded image, runs it through the Groq
vision model (see ``ReceiptService``), and returns a transaction draft. Nothing
is saved. The draft just feeds the transaction form or the assistant's propose
and confirm flow.

PII NOTE: the uploaded image is read into memory, used to pull out the fields,
then dropped. It never touches disk or the database. See ``receipt_service``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import ReceiptDraft, UserInDB
from server.src.limiter import limiter
from server.src.services.auth_service import AuthService
from server.src.services.categorization_service import CategorizationService
from server.src.services.receipt_service import (
    ALLOWED_CONTENT_TYPES,
    MAX_IMAGE_BYTES,
    ReceiptService,
)
from server.src.settings import settings

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/scan/", response_model=ReceiptDraft)
@limiter.limit(settings.receipt_scan_rate_limit)
async def scan_receipt(
    request: Request,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Upload a PNG, JPEG, or WebP image.",
        )

    # Reject oversize uploads using the declared size before buffering anything.
    if file.size is not None and file.size > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum receipt size is 5 MB.",
        )

    # Read at most one byte past the limit so a lying/absent Content-Length can't
    # exhaust memory; anything larger is rejected without holding the full body.
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum receipt size is 5 MB.",
        )

    try:
        draft = ReceiptService().extract(data, content_type)
    except Exception:
        # Vision/network errors must never leak internals; fail gracefully.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read the receipt. Please enter the transaction manually.",
        )

    # If the model didn't supply a category, fall back to our categorizer
    # (learned mapping → keyword rule → default) using the merchant as the title.
    if not draft.get("category") and draft.get("title"):
        draft["category"] = CategorizationService(db).categorize(
            current_user.id, draft["title"]
        )[0]

    return draft
