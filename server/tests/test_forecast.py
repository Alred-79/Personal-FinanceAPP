"""Cashflow forecast tests.

Forecast projects the balance forward over a horizon from recurring expenses.
Uses explicit ``start``/``end`` so assertions are deterministic
regardless of when the suite runs.
"""


def _auth_header(client, username="fcuser", email="fc@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "FC User",
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


def test_forecast_no_recurring_is_flat(client):
    headers = _auth_header(client)
    _create_account(client, headers, balance=1000.00)

    resp = client.get(
        "/api/forecast/?start=2026-03-01&end=2026-05-31", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["starting_balance"] == 1000.0
    assert body["ending_balance"] == 1000.0
    assert body["total_projected_expenses"] == 0.0
    assert body["will_go_negative"] is False
    assert len(body["timeline"]) == 1  # just the starting point


def test_forecast_projects_recurring_expenses(client):
    headers = _auth_header(client)
    acct = _create_account(client, headers, balance=1000.00)

    # A $100/month recurring expense anchored in the past. Creating it also
    # subtracts $100 from the account once → balance is now $900.
    resp = client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": "Gym",
            "amount": 100.00,
            "date": "2026-01-15",
            "category": "Health",
            "recurrence": "monthly",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Horizon Mar 1 to May 31 catches the 15th of Mar, Apr, May → 3 × $100.
    body = client.get(
        "/api/forecast/?start=2026-03-01&end=2026-05-31", headers=headers
    ).json()

    assert body["starting_balance"] == 900.0
    assert body["total_projected_expenses"] == 300.0
    assert body["ending_balance"] == 600.0
    assert body["lowest_balance"] == 600.0
    assert body["lowest_date"] == "2026-05-15"
    assert body["will_go_negative"] is False
    assert len(body["timeline"]) == 4  # start + 3 projected charges


def test_forecast_flags_negative_balance(client):
    headers = _auth_header(client)
    acct = _create_account(client, headers, balance=150.00)
    # $100/month recurring; after creation balance is $50.
    client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": "Rent",
            "amount": 100.00,
            "date": "2026-01-15",
            "category": "Housing",
            "recurrence": "monthly",
        },
        headers=headers,
    )
    body = client.get(
        "/api/forecast/?start=2026-03-01&end=2026-04-30", headers=headers
    ).json()
    # Starting $50, minus Mar 15 ($100) → -$50 → goes negative.
    assert body["starting_balance"] == 50.0
    assert body["will_go_negative"] is True
    assert body["lowest_balance"] < 0


def test_forecast_requires_auth(client):
    resp = client.get("/api/forecast/")
    assert resp.status_code == 401
