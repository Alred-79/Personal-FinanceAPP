"""Import Anything — the universal front door over the ingestion pipeline.

The Reconciliation Desk handles a *statement*. But people capture spending from
all sorts of messy sources: a screenshot of a Venmo or Apple Pay feed, a
forwarded order-confirmation email, a single receipt photo, a pasted blob. This
service classifies whatever was dropped and routes it to the right extractor:

* ``statement`` → the full ``ReconciliationService`` pipeline (balance check),
* ``feed``      → the same pipeline, but with no opening/closing balance, so it
                  degrades gracefully to "review all rows" (the reconcile math
                  already handles a balance-less statement),
* ``receipt``   → a single-transaction draft is wrapped as a one-row session so
                  the review/commit UX is identical across every source,
* ``unknown``   → treated as a feed (best-effort extraction); the user reviews.

Classification is one cheap model call, injected (``classify_fn``) so tests run
without Groq — same testability stance as ``receipt_service`` /
``reconciliation_service``. The actual extraction reuses the existing services
wholesale; this layer only decides *which* one to call.
"""

from __future__ import annotations

import base64
import json
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ..db.models import ImportRow as ImportRowORM
from ..db.models import ImportSession as ImportSessionORM
from ..money import dollars_to_cents
from .categorization_service import canonicalize_category, normalize_merchant
from .reconciliation_service import ReconciliationService

# (kind_hint_text, optional_image_b64, optional_content_type) -> one of the
# DOC_KINDS labels. Injected for tests.
ClassifyFn = Callable[[Optional[str], Optional[str], Optional[str]], str]

DOC_KINDS = ("statement", "feed", "receipt", "unknown")

_CLASSIFY_PROMPT = (
    "Classify this financial document into exactly one of: "
    "statement (a bank/card statement with many transactions and balances), "
    "feed (a screenshot or list of payments like Venmo/Apple Pay/PayPal, no "
    "running balance), receipt (a single store purchase), or unknown. "
    "Respond with ONLY a JSON object: {\"kind\": \"statement|feed|receipt|unknown\"}."
)


def _default_classify_fn(
    text: Optional[str], image_b64: Optional[str], content_type: Optional[str]
) -> str:
    """One Groq call to label the document. Lazy import keeps tests SDK-free."""
    from groq import Groq

    from ..settings import settings

    client = Groq(api_key=settings.groq_api_key)
    if image_b64:
        response = client.chat.completions.create(
            model=settings.groq_vision_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _CLASSIFY_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type or 'image/png'};base64,{image_b64}"
                            },
                        },
                    ],
                }
            ],
        )
    else:
        response = client.chat.completions.create(
            model=settings.groq_chat_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _CLASSIFY_PROMPT},
                {"role": "user", "content": text or ""},
            ],
        )
    return _kind_of(response.choices[0].message.content)


def _kind_of(content: Optional[str]) -> str:
    """Parse the classifier's JSON to a known kind; default to 'unknown'."""
    if not content:
        return "unknown"
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return "unknown"
    kind = (data.get("kind") if isinstance(data, dict) else None) or "unknown"
    kind = str(kind).strip().lower()
    return kind if kind in DOC_KINDS else "unknown"


class ImportService:
    """Classify a dropped document, then route it to the right extractor."""

    def __init__(
        self,
        db: Session,
        *,
        classify_fn: Optional[ClassifyFn] = None,
        reconciliation: Optional[ReconciliationService] = None,
    ) -> None:
        self.db = db
        self.classify_fn = classify_fn or _default_classify_fn
        self.reconciliation = reconciliation or ReconciliationService(db)

    def ingest_any(
        self,
        *,
        user_id: int,
        account_id: int,
        raw_bytes: Optional[bytes] = None,
        content_type: Optional[str] = None,
        raw_text: Optional[str] = None,
    ) -> tuple[ImportSessionORM, str]:
        """Classify then dispatch. Returns ``(session, detected_kind)``.

        Every path yields an ``ImportSession`` so the review/commit UX is uniform
        regardless of source. Raises ``ValueError`` if the account isn't the
        user's (surfaced by the reconciliation service's own ownership check).
        """
        image_b64 = (
            base64.b64encode(raw_bytes).decode("ascii") if raw_bytes else None
        )
        kind = self.classify_fn(raw_text, image_b64, content_type)

        if kind == "receipt" and raw_bytes is not None:
            session = self._ingest_receipt(
                user_id, account_id, raw_bytes, content_type
            )
            return session, kind

        # statement | feed | unknown (and a text-only "receipt", which has no
        # image to scan) all go through the reconciliation pipeline. A feed/unknown
        # simply carries no opening/closing balance, so it degrades to "review
        # all rows" — the reconcile math already handles that.
        source_kind = "text" if raw_bytes is None else (
            "pdf" if content_type == "application/pdf" else "image"
        )
        session = self.reconciliation.ingest(
            user_id=user_id,
            account_id=account_id,
            source_kind=source_kind,
            raw_bytes=raw_bytes,
            content_type=content_type,
            raw_text=raw_text,
        )
        return session, kind

    def _ingest_receipt(
        self,
        user_id: int,
        account_id: int,
        raw_bytes: bytes,
        content_type: Optional[str],
    ) -> ImportSessionORM:
        """Scan a single receipt and wrap the draft as a one-row import session.

        Reuses ``ReceiptService`` verbatim, then materializes the draft into the
        same ``ImportSession`` / ``ImportRow`` shape so the user reviews and
        commits it through the identical flow as a statement.
        """
        from .receipt_service import ReceiptService

        # Ownership check mirrors the reconciliation path.
        self.reconciliation._own_account(account_id, user_id)

        draft = ReceiptService().extract(raw_bytes, content_type or "image/png")
        title = (draft.get("title") or "Receipt").strip() or "Receipt"
        amount = draft.get("amount")
        amount_cents = -abs(dollars_to_cents(amount)) if amount is not None else 0
        category = canonicalize_category(draft.get("category") or "Other")
        date = draft.get("date") or ""
        status = "ok" if (amount is not None and date) else "exception"
        reason = None if status == "ok" else "missing_field"

        session = ImportSessionORM(
            user_id=user_id,
            account_id=account_id,
            source_kind="image",
            status="pending_review",
            opening_balance=None,
            closing_balance=None,
            statement_period=None,
            reconciled=0,
            discrepancy_cents=0,
        )
        self.db.add(session)
        self.db.flush()
        self.db.add(
            ImportRowORM(
                session_id=session.id,
                title=title,
                amount=amount_cents,
                date=date,
                category=category,
                merchant_key=normalize_merchant(title),
                running_balance=None,
                status=status,
                reason=reason,
                included=1 if status == "ok" else 0,
            )
        )
        self.db.flush()
        return session
