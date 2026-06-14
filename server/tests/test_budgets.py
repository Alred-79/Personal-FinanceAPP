"""Envelope budget tests.

Pure calc tests (proration, rollover) plus end to end CRUD/summary via the API.
"""

from datetime import date

import pytest

from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    Expense as ExpenseORM,
    User as UserORM,
)
from server.src.services.budget_service import (
    BudgetService,
    apply_rollover,
    prorate_limit,
)


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


def _create_account(client, headers, balance=1000.00, name="Checking"):
    resp = client.post(
        "/api/accounts/",
        json={"name": name, "type": "checking", "balance": balance},
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
        _create_account(client, headers, balance=500.00, name="Checking")
        _create_account(client, headers, balance=250.00, name="Savings")

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


# ── Step 06: first-month rollover phantom surplus ──────────────────────────────


def _budget_user(db, username="rolluser", email="roll@example.com"):
    user = UserORM(username=username, full_name="Roll", email=email,
                   hashed_password="x", disabled=0)
    db.add(user)
    db.flush()
    acct = AccountORM(name="Checking", type="checking", balance=0, user_id=user.id)
    db.add(acct)
    db.flush()
    return user, acct


def _budget(db, user_id, category="Food", limit_cents=300_00, rollover=True):
    b = BudgetORM(user_id=user_id, category=category,
                  monthly_limit=limit_cents, rollover=1 if rollover else 0)
    db.add(b)
    db.flush()
    return b


def _expense(db, account_id, amount_cents, date_str, category="Food"):
    e = ExpenseORM(title="X", amount=amount_cents, date=date_str,
                   category=category, account_id=account_id)
    db.add(e)
    db.flush()
    return e


class TestRolloverFirstMonth:
    TODAY = date(2026, 3, 10)  # March → prior month is February 2026

    def test_budget_first_month_no_phantom_rollover(self, db_session):
        """A brand-new rollover budget with NO prior-period activity shows
        effective_limit == monthly_limit (no doubled surplus)."""
        user, _acct = _budget_user(db_session)
        _budget(db_session, user.id, rollover=True)

        out = BudgetService(db_session).summarize(user.id, today=self.TODAY)
        assert len(out) == 1
        b = out[0]
        # No phantom rollover: effective == monthly.
        assert b["effective_limit"] == b["monthly_limit"] == 300.0

    def test_prior_underspent_month_rolls_over(self, db_session):
        """A budget WITH a prior under-spent month does roll over: last month's
        surplus (limit − prior_spent) is added to this month's effective limit."""
        user, acct = _budget_user(db_session, "roll2", "roll2@example.com")
        _budget(db_session, user.id, limit_cents=300_00, rollover=True)
        # Prior month (Feb 2026): spent $100 of the $300 → $200 surplus.
        _expense(db_session, acct.id, 100_00, "2026-02-10")

        out = BudgetService(db_session).summarize(user.id, today=self.TODAY)
        b = out[0]
        # 300 + (300 - 100) = 500.
        assert b["effective_limit"] == 500.0

    def test_rollover_disabled_never_credits(self, db_session):
        user, acct = _budget_user(db_session, "roll3", "roll3@example.com")
        _budget(db_session, user.id, limit_cents=300_00, rollover=False)
        _expense(db_session, acct.id, 100_00, "2026-02-10")

        out = BudgetService(db_session).summarize(user.id, today=self.TODAY)
        assert out[0]["effective_limit"] == 300.0
