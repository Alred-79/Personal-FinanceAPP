"""Subscription detection tests.

Pure-function detection over fixture transactions, plus the ORM wrapper.
"""

from datetime import date

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    User as UserORM,
)
from server.src.services.subscription_service import (
    detect_subscriptions,
    SubscriptionService,
)


def _monthly_fixture(merchant="Netflix", amount=15.99):
    return [
        {"title": merchant, "amount": amount, "date": "2026-01-15"},
        {"title": merchant, "amount": amount, "date": "2026-02-15"},
        {"title": merchant, "amount": amount, "date": "2026-03-15"},
    ]


class TestDetectSubscriptions:
    def test_detects_monthly(self):
        subs = detect_subscriptions(_monthly_fixture(), as_of=date(2026, 3, 20))
        assert len(subs) == 1
        s = subs[0]
        assert s["cadence"] == "monthly"
        assert s["occurrences"] == 3
        assert s["last_date"] == "2026-03-15"
        assert s["next_date"] == "2026-04-15"
        assert abs(s["amount"] - 15.99) < 0.01

    def test_detects_weekly(self):
        txns = [
            {"title": "Gym", "amount": 10.0, "date": "2026-03-01"},
            {"title": "Gym", "amount": 10.0, "date": "2026-03-08"},
            {"title": "Gym", "amount": 10.0, "date": "2026-03-15"},
        ]
        subs = detect_subscriptions(txns, as_of=date(2026, 3, 20))
        assert len(subs) == 1
        assert subs[0]["cadence"] == "weekly"
        assert subs[0]["next_date"] == "2026-03-22"

    def test_ignores_one_off(self):
        txns = [{"title": "Random Store", "amount": 40.0, "date": "2026-02-10"}]
        assert detect_subscriptions(txns, as_of=date(2026, 3, 20)) == []

    def test_ignores_irregular_amounts(self):
        txns = [
            {"title": "Corner Shop", "amount": 10.0, "date": "2026-01-01"},
            {"title": "Corner Shop", "amount": 95.0, "date": "2026-02-01"},
            {"title": "Corner Shop", "amount": 50.0, "date": "2026-03-01"},
        ]
        assert detect_subscriptions(txns, as_of=date(2026, 3, 20)) == []

    def test_ignores_irregular_cadence(self):
        txns = [
            {"title": "Sporadic", "amount": 10.0, "date": "2026-01-01"},
            {"title": "Sporadic", "amount": 10.0, "date": "2026-01-03"},
            {"title": "Sporadic", "amount": 10.0, "date": "2026-03-01"},
        ]
        assert detect_subscriptions(txns, as_of=date(2026, 3, 20)) == []

    def test_excludes_income_like_negatives(self):
        txns = [
            {"title": "Refund", "amount": -10.0, "date": "2026-01-15"},
            {"title": "Refund", "amount": -10.0, "date": "2026-02-15"},
        ]
        assert detect_subscriptions(txns, as_of=date(2026, 3, 20)) == []


class TestSubscriptionService:
    def test_list_from_db(self, db_session):
        user = UserORM(
            username="bob", full_name="Bob", email="bob@example.com", hashed_password="x"
        )
        db_session.add(user)
        db_session.flush()
        acct = AccountORM(name="Checking", type="depository", balance=0, user_id=user.id)
        db_session.add(acct)
        db_session.flush()
        for d in ("2026-01-15", "2026-02-15", "2026-03-15"):
            db_session.add(
                ExpenseORM(
                    title="Netflix",
                    amount=1599,  # cents
                    date=d,
                    category="Entertainment",
                    account_id=acct.id,
                )
            )
        db_session.flush()

        subs = SubscriptionService(db_session).list_subscriptions(
            user.id, as_of=date(2026, 3, 20)
        )
        assert len(subs) == 1
        assert subs[0]["title"] == "Netflix"
        assert subs[0]["cadence"] == "monthly"
        assert subs[0]["next_date"] == "2026-04-15"
