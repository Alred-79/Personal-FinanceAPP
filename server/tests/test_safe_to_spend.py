"""Safe-to-Spend tests (v1 Feature 3).

The number is dynamic (recomputed per call) and anchored (default horizon =
next projected paycheck). Components are config-gated per user; earmarks
(Goal.progress) reduce it; daily_plan = available / days_remaining.

Service-level tests pin ``as_of`` so the horizon math is deterministic.
"""

from datetime import date

import pytest

from server.src.db.models import Account, Expense, Goal, Income, User
from server.src.models import UserInDB
from server.src.services.spend_service import SpendService


@pytest.fixture
def s2s_user(db_session):
    user = User(
        username="s2s_user",
        full_name="S2S User",
        email="s2s@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    account = Account(
        name="Checking", type="checking", balance=100_000, user_id=user.id
    )  # $1,000
    db_session.add(account)
    db_session.flush()
    return user, account


def _as_user_in_db(user: User) -> UserInDB:
    return UserInDB(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=False,
        spend_warning=user.spend_warning or 20,
        savings_percent=user.savings_percent or 10,
        hashed_password="x",
    )


AS_OF = date(2026, 3, 10)


def _seed_paycheck(db_session, account, anchor="2026-03-01", amount=200_000):
    db_session.add(
        Income(
            title="Paycheck",
            amount=amount,  # $2,000
            date=anchor,
            category="Work",
            recurrence="bi-weekly",
            account_id=account.id,
        )
    )
    db_session.flush()


class TestHorizon:
    def test_horizon_is_next_paycheck(self, db_session, s2s_user):
        user, account = s2s_user
        _seed_paycheck(db_session, account)  # paydays 3/15, 3/29 …
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-15"
        assert out["horizon_source"] == "paycheck"
        assert out["days_remaining"] == 5

    def test_no_paycheck_falls_back_to_end_of_month(self, db_session, s2s_user):
        user, _ = s2s_user
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-31"
        assert out["horizon_source"] == "month_fallback"

    def test_week_and_month_horizons(self, db_session, s2s_user):
        user, _ = s2s_user
        user.s2s_horizon = "week"
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-17"
        user.s2s_horizon = "month"
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["horizon_end"] == "2026-03-31"


class TestComponents:
    def test_bills_subtract_and_income_adds(self, db_session, s2s_user):
        user, account = s2s_user
        user.s2s_horizon = "month"  # fixed horizon → 3/31
        db_session.add(
            Expense(
                title="Rent",
                amount=40_000,  # $400 on 3/20
                date="2026-02-20",
                category="Housing",
                recurrence="monthly",
                account_id=account.id,
            )
        )
        _seed_paycheck(db_session, account)  # +$2,000 on 3/15 and 3/29

        svc = SpendService(db_session)
        out = svc.safe_to_spend(_as_user_in_db(user), AS_OF)
        # 1000 − 400 + 4000 = 4600
        assert out["breakdown"]["upcoming_bills"] == 400.0
        assert out["breakdown"]["projected_income"] == 4000.0
        assert out["available"] == 4600.0

        # Toggle income off → 1000 − 400 = 600
        user.s2s_include_income = 0
        db_session.flush()
        out = svc.safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["projected_income"] == 0.0
        assert out["available"] == 600.0

    def test_earmarks_reduce_available(self, db_session, s2s_user):
        user, _ = s2s_user
        user.s2s_horizon = "month"
        db_session.add(
            Goal(
                name="Japan trip",
                amount=100_000,
                date="2027-01-01",
                user_id=user.id,
                progress=25_000,  # $250 earmarked
            )
        )
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["goal_earmarks"] == 250.0
        # Contributions also subtract (a positive number over the horizon).
        assert out["breakdown"]["goal_contributions"] > 0
        assert out["available"] < 1000.0 - 250.0

        # Toggle goals off → plain balance.
        user.s2s_include_goals = 0
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["goal_earmarks"] == 0.0
        assert out["available"] == 1000.0

    def test_buffer_subtracts(self, db_session, s2s_user):
        user, _ = s2s_user
        user.s2s_horizon = "month"
        user.s2s_buffer = 10_000  # $100
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["breakdown"]["buffer"] == 100.0
        assert out["available"] == 900.0

    def test_daily_plan_is_available_over_days(self, db_session, s2s_user):
        user, account = s2s_user
        _seed_paycheck(db_session, account)  # horizon 3/15, 5 days out
        user.s2s_include_income = 0
        db_session.flush()
        out = SpendService(db_session).safe_to_spend(_as_user_in_db(user), AS_OF)
        assert out["days_remaining"] == 5
        assert out["daily_plan"] == out["available"] / 5


class TestEndpointAndSettings:
    def test_endpoint_and_gear_roundtrip(self, client):
        resp = client.post(
            "/api/signup/",
            json={
                "username": "s2sapi",
                "email": "s2sapi@example.com",
                "full_name": "S2S Api",
                "password": "Test-password1",
            },
        )
        assert resp.status_code == 200, resp.text
        headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        client.cookies.clear()
        client.post(
            "/api/accounts/",
            json={"name": "Checking", "type": "checking", "balance": 500.0},
            headers=headers,
        )

        resp = client.get("/api/spend/safe-to-spend/", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {"available", "horizon_end", "days_remaining", "daily_plan", "breakdown"} <= set(body)

        # The gear: change the rules behind the number.
        resp = client.put(
            "/api/settings/preferences/",
            json={"s2s_horizon": "week", "s2s_buffer": 50.0, "birth_year": 1999},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        prefs = resp.json()
        assert prefs["s2s_horizon"] == "week"
        assert prefs["s2s_buffer"] == 50.0
        assert prefs["birth_year"] == 1999

        body2 = client.get("/api/spend/safe-to-spend/", headers=headers).json()
        assert body2["config"]["horizon"] == "week"
        assert body2["available"] == body["available"] - 50.0  # buffer bites

        # Invalid horizon rejected.
        resp = client.put(
            "/api/settings/preferences/",
            json={"s2s_horizon": "fortnight"},
            headers=headers,
        )
        assert resp.status_code == 422
