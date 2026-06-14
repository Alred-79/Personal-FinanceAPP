"""Pillar 3 Phase 2 — tax-document ingestion (the acute PII surface).

Pattern from ``test_receipts.py``: inject ``vision_fn`` so no Groq SDK is needed.
The non-negotiable invariants:
  * W-2/1099 money boxes normalize to integer cents,
  * the document BYTES are never persisted (no raw_* column anywhere),
  * the FULL SSN/EIN is NEVER in storage — only a masked ``last4`` survives,
    even when a malicious/sloppy vision_fn hands back a full identifier,
  * the import classifier routes a ``tax_form`` to the tax-doc path (it does NOT
    become transaction rows), and
  * the EIN redaction rule is correct AND doesn't regress account redaction.
"""

from __future__ import annotations

import json

from sqlalchemy import inspect, select

from server.src.db.models import TaxDocument as TaxDocumentORM, User as UserORM
from server.src.services.import_service import (
    ImportService,
    TaxFormDetected,
)
from server.src.services.pii import scrub_secrets
from server.src.services.tax.tax_doc_service import TaxDocService
from server.src.services.tax.tax_document_store import TaxDocumentStore


def _user(db, username="alice"):
    u = UserORM(
        username=username,
        full_name="Alice",
        email=f"{username}@example.com",
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    return u


# ── EIN redaction rule (pii.py) ──────────────────────────────────────────────

class TestEinRedaction:
    def test_dashed_ein_redacted(self):
        assert scrub_secrets("EIN 12-3456789") == "EIN [REDACTED_EIN]"

    def test_bare_nine_digits_still_account(self):
        # The new EIN rule must NOT regress the existing account redaction: a
        # bare 9-digit run (no dash) is still an account.
        assert scrub_secrets("acct 123456789") == "acct [REDACTED_ACCT]"

    def test_ssn_unaffected(self):
        assert scrub_secrets("ssn 123-45-6789") == "ssn [REDACTED_SSN]"


# ── vision extraction → cents, PII masking ───────────────────────────────────

class TestTaxDocExtraction:
    def test_w2_boxes_to_cents(self):
        def vf(b64, ct, form):
            return {
                "issuer_name": "Acme Corp",
                "tin_last4": "6789",
                "tax_year": 2026,
                "box1_wages": 58000.0,
                "box2_fed_withholding": 4100.50,
                "box17_state_withholding": 1200.0,
            }

        out = TaxDocService(vision_fn=vf).extract(b"img", "image/png", "W-2")
        assert out["fields"]["box1_wages"] == 5800000
        assert out["fields"]["box2_fed_withholding"] == 410050
        assert out["fields"]["box17_state_withholding"] == 120000
        assert out["issuer_tin_last4"] == "6789"
        assert out["tax_year"] == 2026

    def test_full_ssn_in_tin_field_is_masked(self):
        """A vision_fn that returns a FULL SSN must be reduced to last 4."""
        def vf(b64, ct, form):
            return {"issuer_name": "Acme", "tin_last4": "123-45-6789", "tax_year": 2026,
                    "box1_compensation": 1000.0}

        out = TaxDocService(vision_fn=vf).extract(b"img", "image/png", "1099-NEC")
        assert out["issuer_tin_last4"] == "6789"
        assert "123-45-6789" not in json.dumps(out)

    def test_ein_in_issuer_name_is_scrubbed(self):
        def vf(b64, ct, form):
            return {"issuer_name": "Acme Corp EIN 12-3456789", "tax_year": 2026,
                    "box1_compensation": 1000.0}

        out = TaxDocService(vision_fn=vf).extract(b"img", "image/png", "1099-NEC")
        assert "12-3456789" not in out["issuer_name"]
        assert "[REDACTED_EIN]" in out["issuer_name"]

    def test_meals_term_label_kept_for_1099b(self):
        def vf(b64, ct, form):
            return {"issuer_name": "Broker", "tax_year": 2026, "proceeds": 5000.0,
                    "cost_basis": 4200.0, "term": "long"}

        out = TaxDocService(vision_fn=vf).extract(b"img", "image/png", "1099-B")
        assert out["fields"]["proceeds"] == 500000
        assert out["fields"]["cost_basis"] == 420000
        assert out["fields"]["term"] == "long"


# ── storage: bytes never persisted, full id never stored ─────────────────────

class TestTaxDocStorage:
    def test_no_raw_bytes_column_anywhere(self):
        cols = {c.name for c in TaxDocumentORM.__table__.columns}
        # No raw_* / blob / image column — bytes are never persisted.
        assert not any(c.startswith("raw") for c in cols)
        assert "image" not in cols and "bytes" not in cols and "blob" not in cols

    def test_store_scrubs_and_masks(self, db_session):
        db = db_session
        u = _user(db)
        store = TaxDocumentStore(db)
        # Even if the caller passes a full SSN/EIN, storage must never hold it.
        doc = store.create_pending(
            u.id,
            form_type="1099-NEC",
            issuer_name="Acme EIN 12-3456789",
            issuer_tin_last4="123-45-6789",  # full SSN passed in
            tax_year=2026,
            fields={"box1_compensation": 5800000, "box4_fed_withholding": 410000},
        )
        db.flush()
        fresh = db.execute(
            select(TaxDocumentORM).where(TaxDocumentORM.id == doc.id)
        ).scalar_one()
        assert fresh.issuer_tin_last4 == "6789"  # last 4 only
        assert "12-3456789" not in fresh.issuer_name
        assert "[REDACTED_EIN]" in fresh.issuer_name
        # fields_json holds integer cents only.
        boxes = json.loads(fresh.fields_json)
        assert boxes["box1_compensation"] == 5800000
        assert fresh.status == "pending_review"

    def test_patch_then_confirm(self, db_session):
        db = db_session
        u = _user(db)
        store = TaxDocumentStore(db)
        doc = store.create_pending(
            u.id, form_type="W-2", issuer_name="Acme", issuer_tin_last4="6789",
            tax_year=2026, fields={"box1_wages": 5000000},
        )
        # Fix a misread box (cents in at the store layer).
        store.patch(u.id, doc.id, fields={"box1_wages": 5800000})
        assert json.loads(doc.fields_json)["box1_wages"] == 5800000
        # Confirm flips status.
        store.confirm(u.id, doc.id)
        assert doc.status == "confirmed"
        assert doc.confirmed_at is not None

    def test_cannot_confirm_discarded(self, db_session):
        import pytest

        db = db_session
        u = _user(db)
        store = TaxDocumentStore(db)
        doc = store.create_pending(
            u.id, form_type="W-2", issuer_name="Acme", issuer_tin_last4="6789",
            tax_year=2026, fields={"box1_wages": 1},
        )
        store.discard(u.id, doc.id)
        with pytest.raises(ValueError):
            store.confirm(u.id, doc.id)

    def test_ownership_scoped(self, db_session):
        db = db_session
        alice = _user(db, "alice")
        bob = _user(db, "bob")
        store = TaxDocumentStore(db)
        doc = store.create_pending(
            alice.id, form_type="W-2", issuer_name="Acme", issuer_tin_last4="6789",
            tax_year=2026, fields={"box1_wages": 1},
        )
        assert store.get(bob.id, doc.id) is None  # bob can't see alice's doc


# ── import classifier routes a tax form to the tax path ──────────────────────

class TestImportClassifyRoutesTaxForm:
    def test_tax_form_raises_redirect(self, db_session):
        import pytest

        db = db_session
        u = _user(db)
        from server.src.db.models import Account as AccountORM

        acct = AccountORM(name="Checking", type="depository", balance=0, user_id=u.id)
        db.add(acct)
        db.flush()

        # Inject a classifier that labels the drop a tax form.
        def classify_fn(text, image_b64, content_type):
            return "tax_form"

        svc = ImportService(db, classify_fn=classify_fn)
        with pytest.raises(TaxFormDetected):
            svc.ingest_any(
                user_id=u.id,
                account_id=acct.id,
                raw_bytes=b"fake-w2-image",
                content_type="image/png",
            )

    def test_tax_form_is_a_doc_kind(self):
        from server.src.services.import_service import DOC_KINDS

        assert "tax_form" in DOC_KINDS
