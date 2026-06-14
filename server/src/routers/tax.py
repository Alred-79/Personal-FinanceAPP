"""Tax router — Pillar 3 (tax & messy-data layer).

The HTTP seam for the tax-organization surface. This ORGANIZES, SUMMARIZES, and
ESTIMATES the user's own numbers; it never gives tax advice. The whole surface
is gated on ``settings.tax_features_enabled`` (a guard dependency 404s every
route when the feature is off), and the document-commit reuses the assistant's
propose→confirm token machinery (the ``confirm_tax_document`` action) rather
than duplicating a write path — exactly as the import commit reuses
``commit_import_session``.

Phase 1 routes (tax-bucket tagging):
* ``GET    /tax/buckets/``                       — the Schedule-C bucket registry
* ``PUT    /tax/tags/{tx_type}/{tx_id}/``        — manual tag (learns source=user)
* ``DELETE /tax/tags/{tx_type}/{tx_id}/``        — remove a tag
* ``GET    /tax/tags/{tx_type}/{tx_id}/``        — read a transaction's tag

Phase 2/3 routes (documents, mileage, summary) are added in their phases.
"""

import json
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
from server.src.models import (
    MileageLogIn,
    MileageLogOut,
    TaxBucketOut,
    TaxDocumentOut,
    TaxDocumentPatchIn,
    TaxTagIn,
    TaxTagOut,
    UserInDB,
)
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.services import llm_budget
from server.src.services.auth_service import AuthService
from server.src.services.tax.buckets import TAX_BUCKETS, bucket_label, canonicalize_bucket
from server.src.services.tax.tagging_service import TaxTaggingService, tax_year_for
from server.src.services.tax.tax_doc_service import (
    ALLOWED_CONTENT_TYPES,
    FORM_TYPES,
    TaxDocService,
)
from server.src.services.tax.tax_document_store import TaxDocumentStore
from server.src.settings import settings

router = APIRouter(prefix="/tax", tags=["tax"])

CurrentUser = Annotated[UserInDB, Depends(AuthService.get_current_active_user)]


def _require_enabled() -> None:
    """404 the whole tax surface when the feature flag is off."""
    if not settings.tax_features_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tax features are not enabled."
        )


# Applied to every route so a disabled instance never exposes a tax endpoint.
router.dependencies.append(Depends(_require_enabled))


def _irs_line(bucket: str) -> str:
    spec = TAX_BUCKETS.get(bucket)
    return spec["irs_line"] if spec else ""


def _tag_out(tag) -> TaxTagOut:
    return TaxTagOut(
        id=tag.id,
        tx_type=tag.tx_type,
        tx_id=tag.tx_id,
        tax_year=tag.tax_year,
        bucket=tag.bucket,
        bucket_label=bucket_label(tag.bucket),
        irs_line=_irs_line(tag.bucket),
        business_personal=tag.business_personal,
        deductible_bps=tag.deductible_bps,
        source=tag.source,
        note=tag.note,
    )


@router.get("/buckets/", response_model=list[TaxBucketOut])
def list_buckets(current_user: CurrentUser) -> list[TaxBucketOut]:
    """The Schedule-C bucket registry (for the UI dropdown). Static, code-owned."""
    return [
        TaxBucketOut(
            key=key,
            label=spec["label"],
            irs_line=spec["irs_line"],
            default_deductible_bps=spec["default_deductible_bps"],
            kind=spec["kind"],
        )
        for key, spec in TAX_BUCKETS.items()
    ]


def _validate_tx_type(tx_type: str) -> str:
    if tx_type not in ("expense", "income"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tx_type must be 'expense' or 'income'",
        )
    return tx_type


@router.get("/tags/{tx_type}/{tx_id}/", response_model=TaxTagOut)
def get_tag(
    tx_type: str,
    tx_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> TaxTagOut:
    _validate_tx_type(tx_type)
    # Ownership: the tag must belong to this user.
    from sqlalchemy import select

    from server.src.db.models import TaxTag as TaxTagORM

    tag = db.execute(
        select(TaxTagORM).where(
            TaxTagORM.tx_type == tx_type,
            TaxTagORM.tx_id == tx_id,
            TaxTagORM.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tag.")
    return _tag_out(tag)


@router.put("/tags/{tx_type}/{tx_id}/", response_model=TaxTagOut)
def put_tag(
    tx_type: str,
    tx_id: int,
    body: TaxTagIn,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> TaxTagOut:
    """Manually tag a transaction with a Schedule-C bucket (learns source=user)."""
    _validate_tx_type(tx_type)
    canon = canonicalize_bucket(body.bucket)
    if not canon:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown tax bucket: {body.bucket!r}",
        )
    if body.business_personal not in ("business", "personal"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="business_personal must be 'business' or 'personal'",
        )

    svc = TaxTaggingService(db)
    row = svc.owned_transaction(current_user.id, tx_type, tx_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found."
        )
    tag = svc.tag(
        current_user.id,
        tx_type=tx_type,
        tx_id=tx_id,
        tax_year=tax_year_for(row.date),
        bucket=canon,
        business_personal=body.business_personal,
        deductible_bps=body.deductible_bps,
        source="user",
        note=body.note,
    )
    svc.learn(current_user.id, row.title, tag.bucket, source="user")
    db.commit()
    return _tag_out(tag)


@router.delete("/tags/{tx_type}/{tx_id}/")
def delete_tag(
    tx_type: str,
    tx_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    _validate_tx_type(tx_type)
    removed = TaxTaggingService(db).untag(current_user.id, tx_type, tx_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tag.")
    db.commit()
    return {"message": "Tag removed"}


# ── tax documents (W-2 / 1099-* / 1098) — confirm-then-write ─────────────────


def _doc_out(doc) -> TaxDocumentOut:
    """Serialize a TaxDocument, converting money boxes cents → dollars at the
    boundary. ``issuer_tin_last4`` is the ONLY identifier ever echoed."""
    stored = json.loads(doc.fields_json or "{}")
    fields: dict = {}
    for key, value in stored.items():
        if key == "term":  # non-money label
            fields[key] = value
        elif isinstance(value, int):
            fields[key] = cents_to_dollars(value)
        else:
            fields[key] = value
    return TaxDocumentOut(
        id=doc.id,
        tax_year=doc.tax_year,
        form_type=doc.form_type,
        issuer_name=doc.issuer_name,
        issuer_tin_last4=doc.issuer_tin_last4,
        fields=fields,
        status=doc.status,
        source_kind=doc.source_kind,
    )


@router.post("/documents/extract/", response_model=TaxDocumentOut)
@limiter.limit(settings.import_extract_rate_limit)
async def extract_tax_document(
    request: Request,
    current_user: CurrentUser,
    form_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a tax form → a ``pending_review`` TaxDocument review payload.

    Same guards as the import extract path: content-type allowlist,
    ``import_max_bytes``, and ``llm_budget.check_and_reserve`` with refund on
    failure. The uploaded bytes live only in memory for the request and are
    NEVER persisted; only the PII-scrubbed, last-4-only review row is stored.
    Commit happens via ``/assistant/actions/propose|confirm`` with the
    ``confirm_tax_document`` action.
    """
    if form_type not in FORM_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"form_type must be one of {sorted(FORM_TYPES)}",
        )
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Upload a PNG, JPEG, WebP, or PDF.",
        )
    if file.size is not None and file.size > settings.import_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large.",
        )
    data = await file.read(settings.import_max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.import_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large.",
        )

    try:
        llm_budget.check_and_reserve(db, current_user.id, requests=1)
    except llm_budget.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    try:
        extracted = TaxDocService().extract(data, content_type, form_type)
    except Exception:
        llm_budget.release_request(db, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read the tax form. Please try a clearer file.",
        )
    finally:
        # Defense in depth: drop the bytes reference promptly.
        del data

    source_kind = "pdf" if content_type == "application/pdf" else "image"
    doc = TaxDocumentStore(db).create_pending(
        current_user.id,
        form_type=extracted["form_type"],
        issuer_name=extracted["issuer_name"],
        issuer_tin_last4=extracted["issuer_tin_last4"],
        tax_year=extracted["tax_year"],
        fields=extracted["fields"],
        source_kind=source_kind,
    )
    db.commit()
    return _doc_out(doc)


@router.get("/documents/", response_model=list[TaxDocumentOut])
def list_tax_documents(
    current_user: CurrentUser,
    tax_year: Optional[int] = None,
    db: Session = Depends(get_db),
) -> list[TaxDocumentOut]:
    docs = TaxDocumentStore(db).list(current_user.id, tax_year)
    return [_doc_out(d) for d in docs]


@router.get("/documents/{doc_id}/", response_model=TaxDocumentOut)
def get_tax_document(
    doc_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> TaxDocumentOut:
    doc = TaxDocumentStore(db).get(current_user.id, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return _doc_out(doc)


@router.patch("/documents/{doc_id}/", response_model=TaxDocumentOut)
def patch_tax_document(
    doc_id: int,
    body: TaxDocumentPatchIn,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> TaxDocumentOut:
    """Fix a misread box BEFORE confirming. Money values come in as DOLLARS and
    are converted to integer cents here; the store re-scrubs every string."""
    fields_cents: Optional[dict] = None
    if body.fields is not None:
        fields_cents = {}
        for key, value in body.fields.items():
            if key == "term":
                fields_cents[key] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                fields_cents[key] = dollars_to_cents(float(value))
    try:
        doc = TaxDocumentStore(db).patch(
            current_user.id,
            doc_id,
            tax_year=body.tax_year,
            issuer_name=body.issuer_name,
            fields=fields_cents,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    db.commit()
    return _doc_out(doc)


# ── mileage log (business miles → IRS-rate deduction) ────────────────────────


def _mileage_out(row) -> MileageLogOut:
    return MileageLogOut(
        id=row.id,
        trip_date=row.trip_date,
        miles=row.miles_milli / 1000,
        purpose=row.purpose,
        business_personal=row.business_personal,
        tax_year=row.tax_year,
    )


@router.post("/mileage/", response_model=MileageLogOut)
def add_mileage(
    body: MileageLogIn,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> MileageLogOut:
    from server.src.db.models import MileageLog as MileageLogORM

    if body.business_personal not in ("business", "personal"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="business_personal must be 'business' or 'personal'",
        )
    try:
        year = tax_year_for(body.trip_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    row = MileageLogORM(
        user_id=current_user.id,
        trip_date=body.trip_date,
        miles_milli=round(body.miles * 1000),  # miles×1000, integer discipline
        purpose=body.purpose,
        business_personal=body.business_personal,
        tax_year=year,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _mileage_out(row)


@router.get("/mileage/", response_model=list[MileageLogOut])
def list_mileage(
    current_user: CurrentUser,
    tax_year: Optional[int] = None,
    db: Session = Depends(get_db),
) -> list[MileageLogOut]:
    from sqlalchemy import select as _select

    from server.src.db.models import MileageLog as MileageLogORM

    stmt = _select(MileageLogORM).where(MileageLogORM.user_id == current_user.id)
    if tax_year is not None:
        stmt = stmt.where(MileageLogORM.tax_year == tax_year)
    rows = db.execute(stmt).scalars().all()
    return [_mileage_out(r) for r in rows]


@router.delete("/mileage/{log_id}/")
def delete_mileage(
    log_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    from server.src.db.models import MileageLog as MileageLogORM

    row = db.get(MileageLogORM, log_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    db.delete(row)
    db.commit()
    return {"message": "Mileage log removed"}


# ── tax summary (read; dollars at the boundary) ──────────────────────────────


@router.get("/summary/{tax_year}/")
def get_summary(
    tax_year: int,
    current_user: CurrentUser,
    filing_status: str = "single",
    state_rate_pct: float = 0.0,
    prior_year_tax: Optional[float] = None,
    payments_made: float = 0.0,
    db: Session = Depends(get_db),
) -> dict:
    """The full tax-organization summary for a year, money in DOLLARS.

    Organization only — not tax advice. The figures are the user's own tagged
    numbers; the quarterly figure is a labelled two-lane estimate (self-employment
    tax + bracketed federal income tax). Estimate inputs are query params so the
    page can recompute as the user picks a filing status / enters a state rate:

    * ``filing_status`` — single | mfj | mfs | hoh (defaults to single).
    * ``state_rate_pct`` — flat state rate as a PERCENT (e.g. 5 = 5%); 0 skips state.
    * ``prior_year_tax`` — last year's total tax (DOLLARS) → enables the safe-harbor
      target; omit to leave safe harbor null.
    * ``payments_made`` — estimated payments already sent this year (DOLLARS).
    """
    from server.src.services.tax.summary_service import TaxSummaryService

    if filing_status not in ("single", "mfj", "mfs", "hoh"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="filing_status must be one of single, mfj, mfs, hoh",
        )
    if not (0.0 <= state_rate_pct <= 20.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="state_rate_pct must be between 0 and 20",
        )

    summary = TaxSummaryService(db).get_tax_summary(
        current_user.id,
        tax_year,
        filing_status=filing_status,
        state_rate_bps=round(state_rate_pct * 100),  # percent → basis points
        prior_year_tax_cents=(
            dollars_to_cents(prior_year_tax) if prior_year_tax is not None else None
        ),
        payments_made_cents=dollars_to_cents(max(0.0, payments_made)),
    )
    return _summary_to_dollars(summary)


def _summary_to_dollars(summary: dict) -> dict:
    """Convert every ``*_cents`` figure to a dollar field at the API boundary.

    A ``*_cents`` key carrying ``None`` (e.g. an unset safe-harbor target) still
    gets its suffix stripped so the dollar-named field is consistently present and
    simply ``null`` — the frontend never sees a leftover ``*_cents`` key.
    """

    def conv(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k.endswith("_cents") and isinstance(v, int):
                    out[k[:-6]] = cents_to_dollars(v)
                elif k.endswith("_cents") and v is None:
                    out[k[:-6]] = None
                else:
                    out[k] = conv(v)
            return out
        if isinstance(obj, list):
            return [conv(x) for x in obj]
        return obj

    result = conv(summary)
    assert isinstance(result, dict)
    return result
