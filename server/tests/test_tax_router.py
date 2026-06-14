"""Pillar 3 — the tax router (HTTP seam).

Manual tag PUT/DELETE, the bucket registry, the doc extract/patch + confirm flow
(propose→confirm reuse), mileage CRUD, the summary read, the feature-flag gate
(404 when off), and ownership scoping.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _tax_on(monkeypatch):
    """Enable the tax feature for this module (the router 404s when off)."""
    from server.src.settings import settings
    monkeypatch.setattr(settings, "tax_features_enabled", True, raising=False)
    yield


def _auth(client, username="taxuser", email="tax@example.com"):
    resp = client.post(
        "/api/signup/",
        json={"username": username, "email": email, "full_name": "Tax User",
              "password": "Test-password1"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _account(client, headers):
    client.post("/api/accounts/",
                json={"name": "Checking", "type": "checking", "balance": 1000.0},
                headers=headers)
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


def _expense(client, headers, acct, title="Staples", amount=60.0, date="2026-03-01"):
    client.post("/api/expenses/",
                json={"account_id": acct, "title": title, "amount": amount,
                      "date": date, "category": "Shops"},
                headers=headers)
    return client.get("/api/expenses/", headers=headers).json()[-1]["id"]


# ── feature flag gate ────────────────────────────────────────────────────────

def test_disabled_returns_404(client, monkeypatch):
    from server.src.settings import settings
    monkeypatch.setattr(settings, "tax_features_enabled", False, raising=False)
    headers = _auth(client)
    assert client.get("/api/tax/buckets/", headers=headers).status_code == 404


# ── bucket registry ──────────────────────────────────────────────────────────

def test_buckets_registry(client):
    headers = _auth(client)
    resp = client.get("/api/tax/buckets/", headers=headers)
    assert resp.status_code == 200, resp.text
    keys = {b["key"] for b in resp.json()}
    assert "sch_c_18_office" in keys and "sch_c_24b_meals" in keys


# ── manual tag PUT / GET / DELETE ────────────────────────────────────────────

def test_manual_tag_put_get_delete(client):
    headers = _auth(client)
    acct = _account(client, headers)
    tx = _expense(client, headers, acct)

    put = client.put(f"/api/tax/tags/expense/{tx}/",
                     json={"bucket": "sch_c_18_office"}, headers=headers)
    assert put.status_code == 200, put.text
    assert put.json()["bucket"] == "sch_c_18_office"
    assert put.json()["tax_year"] == 2026

    got = client.get(f"/api/tax/tags/expense/{tx}/", headers=headers)
    assert got.status_code == 200
    assert got.json()["bucket_label"].startswith("Office")

    dele = client.delete(f"/api/tax/tags/expense/{tx}/", headers=headers)
    assert dele.status_code == 200
    assert client.get(f"/api/tax/tags/expense/{tx}/", headers=headers).status_code == 404


def test_tag_rejects_ghost_bucket(client):
    headers = _auth(client)
    acct = _account(client, headers)
    tx = _expense(client, headers, acct)
    resp = client.put(f"/api/tax/tags/expense/{tx}/",
                      json={"bucket": "ghost"}, headers=headers)
    assert resp.status_code == 422


def test_tag_ownership_scoped(client):
    alice = _auth(client, "alice", "alice@e.com")
    acct = _account(client, alice)
    tx = _expense(client, alice, acct)
    bob = _auth(client, "bob", "bob@e.com")
    # Bob can't tag Alice's transaction.
    resp = client.put(f"/api/tax/tags/expense/{tx}/",
                      json={"bucket": "sch_c_18_office"}, headers=bob)
    assert resp.status_code == 404


# ── tag via the assistant propose→confirm flow ───────────────────────────────

def test_tag_action_propose_then_confirm(client, db_session):
    headers = _auth(client)
    acct = _account(client, headers)
    tx = _expense(client, headers, acct)

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={"action": "tag_transaction_tax",
              "params": {"transaction_id": tx, "type": "expense",
                         "bucket": "sch_c_18_office"}},
        headers=headers,
    )
    assert proposal.status_code == 200, proposal.text
    assert "Office" in proposal.json()["summary"]

    # Nothing tagged yet.
    from server.src.db.models import TaxTag as TaxTagORM
    assert db_session.execute(select(TaxTagORM)).scalars().all() == []

    confirm = client.post("/api/assistant/actions/confirm/",
                          json={"token": proposal.json()["token"]}, headers=headers)
    assert confirm.status_code == 200, confirm.text
    db_session.expire_all()
    tag = db_session.execute(select(TaxTagORM)).scalar_one()
    assert tag.bucket == "sch_c_18_office"


# ── tax document extract → patch → confirm ───────────────────────────────────

def _mock_vision(monkeypatch):
    """Swap TaxDocService's default vision_fn so no Groq call happens."""
    import server.src.services.tax.tax_doc_service as mod

    def fake(image_b64, content_type, form_hint):
        return {"issuer_name": "Acme Corp", "tin_last4": "123-45-6789",
                "tax_year": 2026, "box1_compensation": 58000.0,
                "box4_fed_withholding": 4100.0}

    monkeypatch.setattr(mod, "_default_vision_fn", fake)


def test_doc_extract_patch_confirm(client, db_session, monkeypatch):
    _mock_vision(monkeypatch)
    headers = _auth(client)

    resp = client.post(
        "/api/tax/documents/extract/",
        data={"form_type": "1099-NEC"},
        files={"file": ("w2.png", b"fakebytes", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    doc_id = body["id"]
    # PII: only last 4 echoed; box money in dollars.
    assert body["issuer_tin_last4"] == "6789"
    assert "123-45-6789" not in resp.text
    assert body["fields"]["box1_compensation"] == 58000.0
    assert body["status"] == "pending_review"

    # Fix a misread box (dollars in).
    patched = client.patch(f"/api/tax/documents/{doc_id}/",
                           json={"fields": {"box1_compensation": 59000.0}},
                           headers=headers)
    assert patched.status_code == 200, patched.text
    assert patched.json()["fields"]["box1_compensation"] == 59000.0

    # Confirm via the assistant action.
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={"action": "confirm_tax_document", "params": {"document_id": doc_id}},
        headers=headers,
    )
    assert proposal.status_code == 200, proposal.text
    confirm = client.post("/api/assistant/actions/confirm/",
                          json={"token": proposal.json()["token"]}, headers=headers)
    assert confirm.status_code == 200, confirm.text

    final = client.get(f"/api/tax/documents/{doc_id}/", headers=headers)
    assert final.json()["status"] == "confirmed"


def test_doc_extract_rejects_bad_form_type(client, monkeypatch):
    _mock_vision(monkeypatch)
    headers = _auth(client)
    resp = client.post(
        "/api/tax/documents/extract/",
        data={"form_type": "NOT-A-FORM"},
        files={"file": ("x.png", b"x", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 422


# ── mileage CRUD ─────────────────────────────────────────────────────────────

def test_mileage_crud(client):
    headers = _auth(client)
    add = client.post("/api/tax/mileage/",
                      json={"trip_date": "2026-05-01", "miles": 100.0,
                            "purpose": "client visit"},
                      headers=headers)
    assert add.status_code == 200, add.text
    assert add.json()["miles"] == 100.0
    assert add.json()["tax_year"] == 2026
    log_id = add.json()["id"]

    lst = client.get("/api/tax/mileage/?tax_year=2026", headers=headers)
    assert len(lst.json()) == 1

    dele = client.delete(f"/api/tax/mileage/{log_id}/", headers=headers)
    assert dele.status_code == 200
    assert client.get("/api/tax/mileage/", headers=headers).json() == []


# ── summary read ─────────────────────────────────────────────────────────────

def test_summary_read_dollars(client):
    headers = _auth(client)
    acct = _account(client, headers)
    tx = _expense(client, headers, acct, title="Staples", amount=60.0)
    client.put(f"/api/tax/tags/expense/{tx}/",
               json={"bucket": "sch_c_18_office"}, headers=headers)
    resp = client.get("/api/tax/summary/2026/", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Money at the boundary is dollars (no *_cents keys at top level).
    ded = body["deductions_by_bucket"][0]
    assert ded["deductible"] == 60.0  # dollars
    assert "deductible_cents" not in ded
    assert "disclaimer" in body
