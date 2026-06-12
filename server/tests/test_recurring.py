"""Recurring projection math tests.

Pure-function tests for the projection engine: cadence stepping, calendar-month
boundaries (incl. month-end clamping), horizon edges, and unknown cadences.
"""

from datetime import date

import pytest

from server.src.services.recurring_service import (
    _add_months,
    next_occurrence,
    project_occurrences,
)


class TestAddMonths:
    def test_simple(self):
        assert _add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)

    def test_month_end_clamps(self):
        # Jan 31 + 1 month → Feb 28 (2026 is not a leap year)
        assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

    def test_leap_year(self):
        assert _add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)

    def test_year_rollover(self):
        assert _add_months(date(2026, 12, 10), 1) == date(2027, 1, 10)

    def test_multiple_months(self):
        assert _add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)


class TestNextOccurrence:
    @pytest.mark.parametrize(
        "recurrence,expected",
        [
            ("daily", date(2026, 3, 2)),
            ("weekly", date(2026, 3, 8)),
            ("bi-weekly", date(2026, 3, 15)),
            ("monthly", date(2026, 4, 1)),
            ("quarterly", date(2026, 6, 1)),
            ("annually", date(2027, 3, 1)),
        ],
    )
    def test_each_cadence(self, recurrence, expected):
        assert next_occurrence(date(2026, 3, 1), recurrence) == expected

    def test_unknown_returns_none(self):
        assert next_occurrence(date(2026, 3, 1), "every-full-moon") is None


class TestProjectOccurrences:
    def test_anchor_excluded(self):
        # Anchor itself is never returned, even if inside the horizon.
        occ = project_occurrences(
            date(2026, 3, 1), "monthly", date(2026, 1, 1), date(2026, 5, 1)
        )
        assert date(2026, 3, 1) not in occ
        assert occ == [date(2026, 4, 1), date(2026, 5, 1)]

    def test_monthly_boundaries(self):
        occ = project_occurrences(
            date(2026, 1, 31), "monthly", date(2026, 2, 1), date(2026, 4, 30)
        )
        # Month end clamps each step.
        assert occ == [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]

    def test_weekly_count(self):
        occ = project_occurrences(
            date(2026, 3, 1), "weekly", date(2026, 3, 1), date(2026, 3, 31)
        )
        assert occ == [
            date(2026, 3, 8),
            date(2026, 3, 15),
            date(2026, 3, 22),
            date(2026, 3, 29),
        ]

    def test_horizon_end_inclusive(self):
        occ = project_occurrences(
            date(2026, 3, 1), "weekly", date(2026, 3, 1), date(2026, 3, 8)
        )
        assert occ == [date(2026, 3, 8)]

    def test_horizon_start_filters_early(self):
        # Occurrences before horizon_start are skipped but still advance the cursor.
        occ = project_occurrences(
            date(2026, 1, 1), "monthly", date(2026, 3, 1), date(2026, 4, 1)
        )
        assert occ == [date(2026, 3, 1), date(2026, 4, 1)]

    def test_unknown_cadence_empty(self):
        assert (
            project_occurrences(
                date(2026, 3, 1), "fortnightly", date(2026, 1, 1), date(2026, 12, 1)
            )
            == []
        )

    def test_inverted_horizon_empty(self):
        assert (
            project_occurrences(
                date(2026, 3, 1), "daily", date(2026, 5, 1), date(2026, 4, 1)
            )
            == []
        )

    def test_quarterly_and_annually(self):
        assert project_occurrences(
            date(2026, 1, 1), "quarterly", date(2026, 1, 1), date(2026, 12, 31)
        ) == [date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)]
        assert project_occurrences(
            date(2026, 1, 1), "annually", date(2026, 1, 1), date(2029, 1, 1)
        ) == [date(2027, 1, 1), date(2028, 1, 1), date(2029, 1, 1)]


# ---------------------------------------------------------------------------
# v1 Layer A: project_income / project_cashflows (DB-backed)
# ---------------------------------------------------------------------------

from server.src.db.models import Account, Income, Expense, User
from server.src.services.recurring_service import RecurringService


@pytest.fixture
def seeded_user(db_session):
    user = User(
        username="rec_user",
        full_name="Rec User",
        email="rec@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    account = Account(name="Checking", type="checking", balance=100_000, user_id=user.id)
    db_session.add(account)
    db_session.flush()
    return user, account


class TestProjectCashflows:
    def test_project_income_mirrors_expenses(self, db_session, seeded_user):
        user, account = seeded_user
        db_session.add(
            Income(
                title="Paycheck",
                amount=200_000,  # $2,000
                date="2026-03-01",
                category="Work",
                recurrence="bi-weekly",
                account_id=account.id,
            )
        )
        db_session.flush()

        projected = RecurringService(db_session).project_income(
            user.id, date(2026, 3, 2), date(2026, 4, 1)
        )
        assert [p["date"] for p in projected] == ["2026-03-15", "2026-03-29"]
        assert all(p["type"] == "income" for p in projected)
        assert all(p["projected"] is True for p in projected)
        assert projected[0]["amount"] == 2000.0

    def test_non_recurring_income_not_projected(self, db_session, seeded_user):
        user, account = seeded_user
        db_session.add(
            Income(
                title="One-off",
                amount=50_000,
                date="2026-03-01",
                category="Other",
                account_id=account.id,
            )
        )
        db_session.flush()
        assert (
            RecurringService(db_session).project_income(
                user.id, date(2026, 3, 1), date(2026, 6, 1)
            )
            == []
        )

    def test_project_cashflows_merges_and_sorts(self, db_session, seeded_user):
        user, account = seeded_user
        db_session.add_all(
            [
                Income(
                    title="Paycheck",
                    amount=200_000,
                    date="2026-03-01",
                    category="Work",
                    recurrence="monthly",
                    account_id=account.id,
                ),
                Expense(
                    title="Rent",
                    amount=150_000,
                    date="2026-03-05",
                    category="Housing",
                    recurrence="monthly",
                    account_id=account.id,
                ),
            ]
        )
        db_session.flush()

        flows = RecurringService(db_session).project_cashflows(
            user.id, date(2026, 3, 6), date(2026, 5, 6)
        )
        assert [(f["date"], f["type"]) for f in flows] == [
            ("2026-04-01", "income"),
            ("2026-04-05", "expense"),
            ("2026-05-01", "income"),
            ("2026-05-05", "expense"),
        ]

    def test_next_paycheck_date(self, db_session, seeded_user):
        user, account = seeded_user
        db_session.add(
            Income(
                title="Paycheck",
                amount=200_000,
                date="2026-03-01",
                category="Work",
                recurrence="bi-weekly",
                account_id=account.id,
            )
        )
        db_session.flush()
        svc = RecurringService(db_session)
        assert svc.next_paycheck_date(user.id, date(2026, 3, 2)) == date(2026, 3, 15)
        # No recurring income → None
        assert svc.next_paycheck_date(user.id + 999, date(2026, 3, 2)) is None
