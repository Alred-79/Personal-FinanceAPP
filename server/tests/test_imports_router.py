"""Imports router end-to-end: extract → review → patch → commit via the
assistant action endpoints. The Groq vision call is monkeypatched; the commit
path goes through the real propose/confirm token machinery.
"""

from server.src.services import import_service, reconciliation_service


def _auth_header(client, username="imuser", email="im@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Im User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _create_account(client, headers, balance=1000.00):
    resp = client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": balance},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


CLEAN = {
    "opening_balance": 1000.00,
    "closing_balance": 1075.50,
    "period": "March 2026",
    "transactions": [
        {"date": "2026-03-02", "description": "Whole Foods", "amount": -50.00, "running_balance": 950.00},
        {"date": "2026-03-05", "description": "Starbucks #12", "amount": -24.50, "running_balance": 925.50},
        {"date": "2026-03-10", "description": "Payroll", "amount": 150.00, "running_balance": 1075.50},
    ],
}


def _patch_vision(monkeypatch, statement, kind="statement"):
    # The router goes through ImportService (Import Anything), so patch BOTH the
    # classifier (→ kind) and the statement extractor — neither hits Groq.
    monkeypatch.setattr(
        reconciliation_service, "_default_vision_fn", lambda b64, ct: statement
    )
    monkeypatch.setattr(
        import_service, "_default_classify_fn", lambda text, b64, ct: kind
    )


def test_extract_reconciles_and_returns_payload(client, monkeypatch):
    headers = _auth_header(client)
    account_id = _create_account(client, headers)
    _patch_vision(monkeypatch, CLEAN)

    resp = client.post(
        "/api/imports/extract/",
        data={"account_id": str(account_id)},
        files={"file": ("statement.png", b"\x89PNG fake", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    bc = body["balance_check"]
    assert bc["reconciled"] is True
    assert bc["discrepancy"] == 0.0
    assert bc["opening"] == 1000.00 and bc["closing"] == 1075.50
    assert len(body["rows"]) == 3
    assert body["status"] == "pending_review"
    assert body["detected_kind"] == "statement"  # Import Anything classification


def test_full_commit_flow_creates_transactions(client, monkeypatch):
    headers = _auth_header(client)
    account_id = _create_account(client, headers, balance=1000.00)
    _patch_vision(monkeypatch, CLEAN)

    # 1. extract
    session_id = client.post(
        "/api/imports/extract/",
        data={"account_id": str(account_id)},
        files={"file": ("s.png", b"\x89PNG", "image/png")},
        headers=headers,
    ).json()["id"]

    # 2. propose the commit action
    proposed = client.post(
        "/api/assistant/actions/propose/",
        json={"action": "commit_import_session", "params": {"session_id": session_id}},
        headers=headers,
    )
    assert proposed.status_code == 200, proposed.text
    token = proposed.json()["token"]
    assert "session" in proposed.json()["summary"].lower()

    # 3. confirm → transactions created
    confirmed = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": token},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result"]["committed"] == 3

    # transactions now exist on the account
    txns = client.get("/api/transactions/", headers=headers).json()
    titles = {t["title"] for t in (txns if isinstance(txns, list) else txns.get("items", []))}
    assert {"Whole Foods", "Starbucks #12", "Payroll"} <= titles

    # session is now committed; re-confirming the SAME token is rejected (replay)
    replay = client.post(
        "/api/assistant/actions/confirm/", json={"token": token}, headers=headers
    )
    assert replay.status_code == 409


def test_patch_row_reclears_exception_and_rebalances(client, monkeypatch):
    headers = _auth_header(client)
    account_id = _create_account(client, headers)
    # A statement whose 2nd row breaks the running balance → that row flagged.
    tampered = {
        **CLEAN,
        "transactions": [
            CLEAN["transactions"][0],
            {**CLEAN["transactions"][1], "amount": -34.50},  # running still 925.50
            CLEAN["transactions"][2],
        ],
    }
    _patch_vision(monkeypatch, tampered)
    body = client.post(
        "/api/imports/extract/",
        data={"account_id": str(account_id)},
        files={"file": ("s.png", b"\x89PNG", "image/png")},
        headers=headers,
    ).json()
    session_id = body["id"]
    bad_row = next(r for r in body["rows"] if r["status"] == "exception")

    # Fix the amount back to -24.50; the exception flag clears.
    patched = client.patch(
        f"/api/imports/sessions/{session_id}/rows/{bad_row['id']}/",
        json={"amount": -24.50},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    fixed = next(r for r in patched.json()["rows"] if r["id"] == bad_row["id"])
    assert fixed["status"] == "ok"
    assert patched.json()["balance_check"]["reconciled"] is True


def test_extract_reserves_two_budget_units(client, db_session, monkeypatch):
    """E3: import_extract makes TWO paid Groq calls (classify + extract), so it
    must reserve requests=2 — not 1 (the prior under-count). Asserted against the
    persisted llm_usage row after a successful extract."""
    from sqlalchemy import text as _text

    headers = _auth_header(client)
    account_id = _create_account(client, headers)
    _patch_vision(monkeypatch, CLEAN)

    resp = client.post(
        "/api/imports/extract/",
        data={"account_id": str(account_id)},
        files={"file": ("statement.png", b"\x89PNG fake", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    used = db_session.execute(
        _text("SELECT MAX(requests) FROM llm_usage")
    ).scalar()
    assert used == 2  # classify + extract, not 1


def test_extract_requires_auth(client):
    resp = client.post(
        "/api/imports/extract/",
        data={"account_id": "1"},
        files={"file": ("s.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 401


def test_extract_rejects_unsupported_type(client, monkeypatch):
    headers = _auth_header(client)
    account_id = _create_account(client, headers)
    resp = client.post(
        "/api/imports/extract/",
        data={"account_id": str(account_id)},
        files={"file": ("s.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


def test_detangle_endpoint_flags_transfer(client, monkeypatch):
    headers = _auth_header(client)
    chk = _create_account(client, headers, balance=1000.0)
    # second account
    client.post(
        "/api/accounts/",
        json={"name": "Savings", "type": "savings", "balance": 1000.0},
        headers=headers,
    )
    sav = client.get("/api/accounts/", headers=headers).json()[-1]["id"]

    # A transfer: -500 from checking, +500 to savings, same day.
    client.post(
        "/api/expenses/",
        json={"title": "Transfer", "amount": 500.0, "date": "2026-03-01",
              "category": "Transfer", "account_id": chk},
        headers=headers,
    )
    client.post(
        "/api/income/",
        json={"title": "Transfer", "amount": 500.0, "date": "2026-03-01",
              "category": "Transfer", "account_id": sav},
        headers=headers,
    )

    resp = client.post("/api/imports/detangle/run/", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["flagged"] == 1
    # Idempotent: a second run flags nothing new.
    assert client.post("/api/imports/detangle/run/", headers=headers).json()["flagged"] == 0
