"""Transparency router for learned memory (Pillar 1A).

The user can see, correct, and delete what the Clerk has learned. These run via
the API (no Groq).
"""


def _auth_header(client, username="memrouter", email="memr@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Mem Router",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_list_empty_then_put_then_list(client):
    headers = _auth_header(client)
    assert client.get("/api/memory/", headers=headers).json()["items"] == []

    put = client.put(
        "/api/memory/savings_intent/",
        json={"value": "saving for a house by 2028", "pinned": True},
        headers=headers,
    )
    assert put.status_code == 200, put.text

    items = client.get("/api/memory/", headers=headers).json()["items"]
    assert len(items) == 1
    fact = items[0]
    assert fact["key"] == "savings_intent"
    assert "house" in fact["value"]
    assert fact["source"] == "user"
    assert fact["pinned"] is True


def test_put_unknown_key_rejected(client):
    headers = _auth_header(client)
    resp = client.put(
        "/api/memory/not_a_key/", json={"value": "x"}, headers=headers
    )
    assert resp.status_code == 400


def test_put_scrubs_pii(client):
    headers = _auth_header(client)
    client.put(
        "/api/memory/recurring_note/",
        json={"value": "my ssn is 123-45-6789"},
        headers=headers,
    )
    fact = client.get("/api/memory/", headers=headers).json()["items"][0]
    assert "123-45-6789" not in fact["value"]


def test_delete_forgets(client):
    headers = _auth_header(client)
    client.put(
        "/api/memory/tone_preference/", json={"value": "blunt"}, headers=headers
    )
    deleted = client.delete("/api/memory/tone_preference/", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/memory/", headers=headers).json()["items"] == []


def test_delete_missing_is_404(client):
    headers = _auth_header(client)
    assert client.delete("/api/memory/tone_preference/", headers=headers).status_code == 404


def test_memory_is_per_user(client):
    a = _auth_header(client, username="mem_a", email="ma@example.com")
    b = _auth_header(client, username="mem_b", email="mb@example.com")
    client.put("/api/memory/tone_preference/", json={"value": "blunt"}, headers=a)
    # b sees nothing of a's memory.
    assert client.get("/api/memory/", headers=b).json()["items"] == []


def test_recategorize_teaches_a_category_preference(client):
    """The deterministic learning lane: confirming a recategorize writes a fact."""
    headers = _auth_header(client, username="mem_recat", email="memrc@example.com")
    # An account + a transaction to recategorize.
    client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": 1000.0},
        headers=headers,
    )
    acct = client.get("/api/accounts/", headers=headers).json()[-1]["id"]
    client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": "Trader Joes",
            "amount": 42.0,
            "date": "2026-05-01",
            "category": "Other",
        },
        headers=headers,
    )
    tx_id = client.get("/api/expenses/", headers=headers).json()[-1]["id"]

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "recategorize_transaction",
            "params": {"transaction_id": tx_id, "category": "Food", "type": "expense"},
        },
        headers=headers,
    ).json()
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text

    keys = {f["key"] for f in client.get("/api/memory/", headers=headers).json()["items"]}
    assert "category_preference:Food" in keys

