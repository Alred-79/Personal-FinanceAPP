"""Persistence for reviewed tax documents (Pillar 3 Phase 2).

The DB seam between the vision extractor (``tax_doc_service``) and the
confirm-then-write flow. Extraction writes a ``pending_review`` ``TaxDocument``;
a PATCH lets the user fix a misread box; the ``confirm_tax_document`` action
flips it to ``confirmed``.

PII discipline lives here too: every string field written to the row is run
through ``pii.scrub_secrets`` (incl. the EIN rule) so the persisted row is
structurally incapable of holding a full SSN/EIN, and ``fields_json`` carries
ONLY money boxes (integer cents) + a small set of non-PII labels. Bytes never
reach this layer.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import TaxDocument as TaxDocumentORM

from ..pii import scrub_secrets

# Non-money labels we allow inside ``fields_json`` (everything else must be an
# integer-cents money box). Keeps the JSON blob to a known, non-PII shape.
_ALLOWED_LABELS = ("term",)


def _safe_fields(fields: dict) -> dict:
    """Coerce an extraction/patch ``fields`` dict to the safe stored shape.

    Money boxes → ints; allowed labels → scrubbed short strings; anything else is
    dropped. A scrubber pass over every string guarantees no full identifier can
    be smuggled into the blob.
    """
    out: dict = {}
    for key, value in (fields or {}).items():
        k = str(key)
        if k in _ALLOWED_LABELS:
            if isinstance(value, str):
                out[k] = scrub_secrets(value.strip())[:32]
            continue
        # money box — must be an int (cents). Accept int; coerce a clean float.
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[k] = value
        elif isinstance(value, float) and value == int(value):
            out[k] = int(value)
        # non-numeric, non-label values are dropped (defense in depth).
    return out


class TaxDocumentStore:
    """CRUD for ``TaxDocument`` rows with always-on PII scrubbing."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_pending(
        self,
        user_id: int,
        *,
        form_type: str,
        issuer_name: str,
        issuer_tin_last4: Optional[str],
        tax_year: Optional[int],
        fields: dict,
        source_kind: str = "image",
    ) -> TaxDocumentORM:
        """Write a ``pending_review`` row from an extraction payload."""
        doc = TaxDocumentORM(
            user_id=user_id,
            tax_year=tax_year if tax_year is not None else 0,
            form_type=form_type,
            issuer_name=scrub_secrets((issuer_name or "").strip()),
            # last-4 only; scrub then keep only the last 4 digits as a final guard.
            issuer_tin_last4=_safe_last4(issuer_tin_last4),
            fields_json=json.dumps(_safe_fields(fields)),
            status="pending_review",
            source_kind=source_kind,
        )
        self.db.add(doc)
        self.db.flush()
        return doc

    def get(self, user_id: int, doc_id: int) -> Optional[TaxDocumentORM]:
        return self.db.execute(
            select(TaxDocumentORM).where(
                TaxDocumentORM.id == doc_id, TaxDocumentORM.user_id == user_id
            )
        ).scalar_one_or_none()

    def list(self, user_id: int, tax_year: Optional[int] = None) -> list[TaxDocumentORM]:
        stmt = select(TaxDocumentORM).where(TaxDocumentORM.user_id == user_id)
        if tax_year is not None:
            stmt = stmt.where(TaxDocumentORM.tax_year == tax_year)
        return list(self.db.execute(stmt).scalars().all())

    def patch(
        self,
        user_id: int,
        doc_id: int,
        *,
        tax_year: Optional[int] = None,
        issuer_name: Optional[str] = None,
        fields: Optional[dict] = None,
    ) -> TaxDocumentORM:
        """Fix a misread box BEFORE confirming. Only a pending row is editable.

        ``fields`` is a partial override merged onto the stored boxes. All string
        values are re-scrubbed.
        """
        doc = self.get(user_id, doc_id)
        if doc is None:
            raise ValueError("tax document not found")
        if doc.status != "pending_review":
            raise ValueError("only a pending document can be edited")
        if tax_year is not None:
            doc.tax_year = int(tax_year)
        if issuer_name is not None:
            doc.issuer_name = scrub_secrets(issuer_name.strip())
        if fields is not None:
            current = json.loads(doc.fields_json or "{}")
            current.update(_safe_fields(fields))
            doc.fields_json = json.dumps(current)
        self.db.flush()
        return doc

    def confirm(self, user_id: int, doc_id: int) -> TaxDocumentORM:
        """Flip a pending row to ``confirmed`` (the ``confirm_tax_document`` write)."""
        from sqlalchemy import func

        doc = self.get(user_id, doc_id)
        if doc is None:
            raise ValueError("tax document not found")
        if doc.status == "discarded":
            raise ValueError("document was discarded")
        doc.status = "confirmed"
        doc.confirmed_at = func.current_timestamp()
        self.db.flush()
        return doc

    def discard(self, user_id: int, doc_id: int) -> TaxDocumentORM:
        doc = self.get(user_id, doc_id)
        if doc is None:
            raise ValueError("tax document not found")
        doc.status = "discarded"
        self.db.flush()
        return doc


def _safe_last4(value: Optional[str]) -> Optional[str]:
    """Keep ONLY the last 4 digits of an identifier (final storage guard)."""
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[-4:] if digits else None
