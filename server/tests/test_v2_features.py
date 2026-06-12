"""v2 backlog feature tests: analytics aggregation + intra-app transfers."""


def _signup(client, username, email):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "V2 User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    client.cookies.clear()
    return headers


def _account(client, headers, name="Checking", balance=1000.0):
    client.post(
        "/api/accounts/",
        json={"name": name, "type": "checking", "balance": balance},
        headers=headers,
    )
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


def _expense(client, headers, acct, title, amount, day, category):
    resp = client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": title,
            "amount": amount,
            "date": day,
            "category": category,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


class TestAnalyticsAggregation:
    def test_category_by_month_pivot(self, client):
        headers = _signup(client, "anal1", "anal1@example.com")
        acct = _account(client, headers)
        _expense(client, headers, acct, "Latte", 5.0, "2026-01-10", "Food")
        _expense(client, headers, acct, "Pizza", 15.0, "2026-01-20", "Food")
        _expense(client, headers, acct, "Bus", 2.5, "2026-01-15", "Transport")
        _expense(client, headers, acct, "Sushi", 30.0, "2026-02-05", "Food")

        resp = client.get(
            "/api/analytics/spending/?start=2026-01-01&end=2026-02-28&bucket=month",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cells = {(c["bucket"], c["category"]): c for c in body["cells"]}
        assert cells[("2026-01", "Food")]["total"] == 20.0
        assert cells[("2026-01", "Food")]["count"] == 2
        assert cells[("2026-01", "Transport")]["total"] == 2.5
        assert cells[("2026-02", "Food")]["total"] == 30.0
        assert body["totals_by_category"]["Food"] == 50.0
        assert body["totals_by_bucket"]["2026-01"] == 22.5
        assert body["grand_total"] == 52.5

    def test_date_range_and_day_bucket(self, client):
        headers = _signup(client, "anal2", "anal2@example.com")
        acct = _account(client, headers)
        _expense(client, headers, acct, "A", 10.0, "2026-01-10", "Food")
        _expense(client, headers, acct, "B", 20.0, "2026-03-10", "Food")

        resp = client.get(
            "/api/analytics/spending/?start=2026-01-01&end=2026-01-31&bucket=day",
            headers=headers,
        )
        body = resp.json()
        assert body["grand_total"] == 10.0
        assert body["cells"][0]["bucket"] == "2026-01-10"

    def test_user_isolation(self, client):
        headers_a = _signup(client, "anal3", "anal3@example.com")
        acct_a = _account(client, headers_a)
        _expense(client, headers_a, acct_a, "Mine", 10.0, "2026-01-10", "Food")
        headers_b = _signup(client, "anal4", "anal4@example.com")
        _account(client, headers_b)

        body = client.get("/api/analytics/spending/", headers=headers_b).json()
        assert body["grand_total"] == 0.0
        assert body["cells"] == []


class TestTransfers:
    def test_transfer_moves_balance_atomically(self, client):
        headers = _signup(client, "xfer1", "xfer1@example.com")
        a = _account(client, headers, name="Checking", balance=300.0)
        b = _account(client, headers, name="Savings", balance=50.0)

        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": b, "amount": 120.0},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["from"]["balance"] == 180.0
        assert body["to"]["balance"] == 170.0

    def test_insufficient_balance_rejected(self, client):
        headers = _signup(client, "xfer2", "xfer2@example.com")
        a = _account(client, headers, name="Checking", balance=10.0)
        b = _account(client, headers, name="Savings", balance=0.0)
        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": b, "amount": 120.0},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_same_account_rejected(self, client):
        headers = _signup(client, "xfer3", "xfer3@example.com")
        a = _account(client, headers, name="Checking", balance=100.0)
        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": a, "amount": 5.0},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_other_users_account_404(self, client):
        headers_a = _signup(client, "xfer4", "xfer4@example.com")
        a = _account(client, headers_a, name="Checking", balance=100.0)
        headers_b = _signup(client, "xfer5", "xfer5@example.com")
        b = _account(client, headers_b, name="Checking", balance=100.0)
        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": b, "amount": 5.0},
            headers=headers_a,
        )
        assert resp.status_code == 404

    def test_plaid_managed_account_refused(self, client, db_session):
        """An account whose name matches a Plaid token is sync-owned: refuse."""
        headers = _signup(client, "xfer6", "xfer6@example.com")
        a = _account(client, headers, name="Plaid Checking", balance=100.0)
        b = _account(client, headers, name="Cash", balance=0.0)

        # Link a token to the first account by name (the Plaid convention).
        from server.src.db.models import Token, User

        user = db_session.query(User).filter_by(username="xfer6").one()
        db_session.add(Token(user_id=user.id, name="Plaid Checking", key="tok"))
        db_session.commit()

        resp = client.post(
            "/api/accounts/transfer/",
            json={"from_account_id": a, "to_account_id": b, "amount": 5.0},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "synced" in resp.json()["detail"]
