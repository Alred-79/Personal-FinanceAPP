"""Transaction endpoint tests."""

from datetime import date


def _auth_header(client, username="txuser", email="tx@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "TX User",
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


def _today() -> str:
    return date.today().isoformat()


class TestTransactionsList:
    def test_list_authed_returns_paginated_shape(self, client):
        h = _auth_header(client)
        resp = client.get("/api/transactions/", headers=h)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body

    def test_list_unauthenticated_returns_401(self, client):
        client.cookies.clear()
        resp = client.get("/api/transactions/")
        assert resp.status_code == 401

    def test_fresh_user_has_empty_transaction_list(self, client):
        h = _auth_header(client, "empty_user", "empty@x.com")
        resp = client.get("/api/transactions/", headers=h).json()
        assert resp["total"] == 0
        assert resp["items"] == []


class TestIncomeEndpoint:
    def test_post_income_creates_transaction(self, client):
        h = _auth_header(client, "inc_user", "inc@x.com")
        acct = _create_account(client, h)
        resp = client.post(
            "/api/income/",
            json={"title": "Salary", "amount": 3000.0, "date": _today(), "category": "Income", "account_id": acct},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        txns = client.get("/api/transactions/", headers=h).json()
        assert txns["total"] >= 1

    def test_post_income_missing_required_field_returns_422(self, client):
        h = _auth_header(client, "inc2_user", "inc2@x.com")
        resp = client.post("/api/income/", json={"title": "Bad"}, headers=h)
        assert resp.status_code == 422

    def test_post_income_appears_in_transaction_list(self, client):
        h = _auth_header(client, "inc3_user", "inc3@x.com")
        acct = _create_account(client, h)
        client.post(
            "/api/income/",
            json={"title": "Bonus", "amount": 500.0, "date": _today(), "category": "Income", "account_id": acct},
            headers=h,
        )
        items = client.get("/api/transactions/", headers=h).json()["items"]
        titles = [t["title"] for t in items]
        assert "Bonus" in titles


class TestDeleteIncome:
    def test_delete_own_income(self, client):
        h = _auth_header(client, "del_user", "del@x.com")
        acct = _create_account(client, h)
        client.post(
            "/api/income/",
            json={"title": "Dividend", "amount": 200.0, "date": _today(), "category": "Income", "account_id": acct},
            headers=h,
        )
        txns = client.get("/api/transactions/", headers=h).json()
        income_id = next(t["id"] for t in txns["items"] if t["type"] == "income")
        resp = client.delete(f"/api/income/{income_id}/", headers=h)
        assert resp.status_code in (200, 204)

    def test_delete_nonexistent_income_returns_404(self, client):
        h = _auth_header(client, "del2_user", "del2@x.com")
        resp = client.delete("/api/income/99999/", headers=h)
        assert resp.status_code == 404

    def test_transaction_removed_after_delete(self, client):
        h = _auth_header(client, "del3_user", "del3@x.com")
        acct = _create_account(client, h)
        client.post(
            "/api/income/",
            json={"title": "OneTime", "amount": 100.0, "date": _today(), "category": "Income", "account_id": acct},
            headers=h,
        )
        txns = client.get("/api/transactions/", headers=h).json()
        income_id = next(t["id"] for t in txns["items"] if t["type"] == "income")
        client.delete(f"/api/income/{income_id}/", headers=h)
        after = client.get("/api/transactions/", headers=h).json()
        assert after["total"] == 0


class TestTransactionFilters:
    def test_search_filter_q_returns_matching(self, client):
        h = _auth_header(client, "qfilt_user", "qfilt@x.com")
        acct = _create_account(client, h)
        client.post(
            "/api/income/",
            json={"title": "Starbucks paycheck", "amount": 100.0, "date": _today(), "category": "Income", "account_id": acct},
            headers=h,
        )
        resp = client.get("/api/transactions/?q=starbucks", headers=h)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_search_filter_category_returns_only_matching(self, client):
        h = _auth_header(client, "catfilt_user", "catfilt@x.com")
        acct = _create_account(client, h)
        client.post(
            "/api/income/",
            json={"title": "Side job", "amount": 50.0, "date": _today(), "category": "Income", "account_id": acct},
            headers=h,
        )
        resp = client.get("/api/transactions/?category=Income", headers=h)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(t["category"] == "Income" for t in items)
