"""Envelope budget tests.

Pure calc tests (proration, rollover) plus end to end CRUD/summary via the API.
"""

from datetime import date

import pytest

from server.src.services.budget_service import apply_rollover, prorate_limit


# ── pure calc ──────────────────────────────────────────────────────────────


class TestProrateLimit:
    def test_half_month(self):
        assert prorate_limit(30000, 15, 30) == 15000

    def test_full_month(self):
        assert prorate_limit(30000, 30, 30) == 30000

    def test_start_of_month(self):
        assert prorate_limit(30000, 0, 30) == 0

    def test_clamps_overflow_days(self):
        # days_elapsed > days_in_month clamps to the full limit.
        assert prorate_limit(30000, 45, 30) == 30000

    def test_rounds_to_nearest_cent(self):
        # 10000 * 1/3 = 3333.33… → 3333
        assert prorate_limit(10000, 1, 3) == 3333

    def test_zero_limit(self):
        assert prorate_limit(0, 15, 30) == 0

    def test_zero_days_in_month_guard(self):
        assert prorate_limit(30000, 5, 0) == 0


class TestApplyRollover:
    def test_surplus_carries_when_enabled(self):
        assert apply_rollover(20000, True, 5000) == 25000

    def test_overspend_does_not_reduce(self):
        assert apply_rollover(20000, True, -5000) == 20000

    def test_disabled_ignores_surplus(self):
        assert apply_rollover(20000, False, 5000) == 20000

    def test_zero_surplus(self):
        assert apply_rollover(20000, True, 0) == 20000


# ── end to end via API ───────────────────────────────────────────────────────


def _auth_header(client, username="buser", email="b@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Budget User",
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


def _today_in_month() -> str:
    """A date guaranteed to fall in the current calendar month."""
    return date.today().replace(day=1).isoformat()


class TestBudgetEndpoints:
    def test_create_and_list_with_spent(self, client):
        headers = _auth_header(client)
        acct = _create_account(client, headers, balance=1000.00)

        # Budget: $300/mo for Food
        resp = client.post(
            "/api/budgets/",
            json={"category": "Food", "monthly_limit": 300.0, "rollover": False},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # Two Food expenses this month totalling $120
        for amt in (50.0, 70.0):
            client.post(
                "/api/expenses/",
                json={
                    "title": "Food",
                    "amount": amt,
                    "date": _today_in_month(),
                    "category": "Food",
                    "account_id": acct,
                },
                headers=headers,
            )

        budgets = client.get("/api/budgets/", headers=headers).json()
        assert len(budgets) == 1
        b = budgets[0]
        assert b["category"] == "Food"
        assert b["monthly_limit"] == 300.0
        assert b["spent"] == 120.0
        assert b["remaining"] == 180.0
        assert b["over_budget"] is False

    def test_over_budget_flag(self, client):
        headers = _auth_header(client)
        acct = _create_account(client, headers, balance=1000.00)
        client.post(
            "/api/budgets/",
            json={"category": "Fun", "monthly_limit": 50.0, "rollover": False},
            headers=headers,
        )
        client.post(
            "/api/expenses/",
            json={
                "title": "Concert",
                "amount": 80.0,
                "date": _today_in_month(),
                "category": "Fun",
                "account_id": acct,
            },
            headers=headers,
        )
        b = client.get("/api/budgets/", headers=headers).json()[0]
        assert b["spent"] == 80.0
        assert b["remaining"] == -30.0
        assert b["over_budget"] is True

    def test_duplicate_category_conflict(self, client):
        headers = _auth_header(client)
        first = client.post(
            "/api/budgets/",
            json={"category": "Rent", "monthly_limit": 1000.0, "rollover": False},
            headers=headers,
        )
        assert first.status_code == 200
        dup = client.post(
            "/api/budgets/",
            json={"category": "Rent", "monthly_limit": 1200.0, "rollover": False},
            headers=headers,
        )
        assert dup.status_code == 409

    def test_update_and_delete(self, client):
        headers = _auth_header(client)
        client.post(
            "/api/budgets/",
            json={"category": "Gas", "monthly_limit": 100.0, "rollover": False},
            headers=headers,
        )
        bid = client.get("/api/budgets/", headers=headers).json()[0]["id"]

        upd = client.put(
            f"/api/budgets/{bid}/",
            json={"category": "Gas", "monthly_limit": 150.0, "rollover": True},
            headers=headers,
        )
        assert upd.status_code == 200
        b = client.get("/api/budgets/", headers=headers).json()[0]
        assert b["monthly_limit"] == 150.0
        assert b["rollover"] is True

        dele = client.delete(f"/api/budgets/{bid}/", headers=headers)
        assert dele.status_code == 200
        assert client.get("/api/budgets/", headers=headers).json() == []

    def test_ownership_isolation(self, client):
        headers_a = _auth_header(client, username="a", email="a@t.com")
        headers_b = _auth_header(client, username="b", email="b@t.com")
        client.post(
            "/api/budgets/",
            json={"category": "Food", "monthly_limit": 300.0, "rollover": False},
            headers=headers_a,
        )
        bid_a = client.get("/api/budgets/", headers=headers_a).json()[0]["id"]

        # B sees no budgets and cannot delete A's.
        assert client.get("/api/budgets/", headers=headers_b).json() == []
        assert (
            client.delete(f"/api/budgets/{bid_a}/", headers=headers_b).status_code
            == 404
        )


class TestNetWorthAndProjection:
    def test_networth_snapshot_and_series(self, client):
        headers = _auth_header(client, username="nw", email="nw@t.com")
        _create_account(client, headers, balance=500.00)
        _create_account(client, headers, balance=250.00)

        series = client.get("/api/networth/", headers=headers).json()
        assert len(series) == 1
        assert series[0]["total"] == 750.0

    def test_projected_expenses(self, client):
        headers = _auth_header(client, username="pj", email="pj@t.com")
        acct = _create_account(client, headers, balance=1000.00)
        # A monthly recurring expense anchored in the past.
        client.post(
            "/api/expenses/",
            json={
                "title": "Netflix",
                "amount": 15.99,
                "date": "2026-01-01",
                "category": "Entertainment",
                "account_id": acct,
                "recurrence": "monthly",
            },
            headers=headers,
        )
        projected = client.get(
            "/api/recurring/projected/?start=2026-02-01&end=2026-04-30",
            headers=headers,
        ).json()
        dates = [p["date"] for p in projected]
        assert dates == ["2026-02-01", "2026-03-01", "2026-04-01"]
        assert all(p["projected"] is True for p in projected)
        assert projected[0]["amount"] == 15.99
