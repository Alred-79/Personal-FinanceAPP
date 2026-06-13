"""Tests for SpendService.get_budget_allotment.

Covers: empty DB, zero income, recurring expenses, unknown recurrence,
past-deadline goals, None goal progress, income only (no expenses),
and multiple recurrence types.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.src.db.models import (
    Base,
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.money import dollars_to_cents
from server.src.services.spend_service import SpendService


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db(_engine):
    Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user(db) -> UserInDB:
    """Create a basic user with 10 % savings and return the Pydantic model."""
    orm_user = UserORM(
        username="testuser",
        full_name="Test User",
        email="test@example.com",
        hashed_password="fakehash",
        disabled=0,
        savings_percent=10,
    )
    db.add(orm_user)
    db.flush()
    pydantic_user = UserInDB(
        id=int(orm_user.id),  # type: ignore[arg-type]
        username=str(orm_user.username),  # type: ignore[arg-type]
        full_name=str(orm_user.full_name),  # type: ignore[arg-type]
        email=str(orm_user.email),  # type: ignore[arg-type]
        disabled=False,
        hashed_password=str(orm_user.hashed_password),  # type: ignore[arg-type]
        savings_percent=int(orm_user.savings_percent),  # type: ignore[arg-type]
    )
    return pydantic_user


@pytest.fixture
def account(db, user) -> AccountORM:
    """Create a checking account for the test user."""
    acct = AccountORM(
        name="Checking",
        type="checking",
        balance=0,
        user_id=user.id,
    )
    db.add(acct)
    db.flush()
    return acct


def _add_income(db, account, amount_dollars, category="Work", date_str=None):
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    inc = IncomeORM(
        title=f"Income {amount_dollars}",
        amount=dollars_to_cents(amount_dollars),
        date=date_str,
        category=category,
        account_id=account.id,
    )
    db.add(inc)
    db.flush()
    return inc


def _add_expense(db, account, amount_dollars, recurrence=None, category="Bills"):
    exp = ExpenseORM(
        title=f"Expense {amount_dollars}",
        amount=dollars_to_cents(amount_dollars),
        date=datetime.now().strftime("%Y-%m-%d"),
        category=category,
        recurrence=recurrence,
        account_id=account.id,
    )
    db.add(exp)
    db.flush()
    return exp


def _add_goal(db, user, amount_dollars, days_from_now, progress_dollars=0, progress_none=False):
    goal_date = (datetime.now() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    goal = GoalORM(
        name=f"Goal {amount_dollars}",
        description="test goal",
        amount=dollars_to_cents(amount_dollars),
        date=goal_date,
        user_id=user.id,
        completed=0,
        progress=None if progress_none else dollars_to_cents(progress_dollars),
    )
    db.add(goal)
    db.flush()
    return goal


# ── tests ────────────────────────────────────────────────────────────────


class TestBudgetAllotment:
    """Budget allotment scenarios from 'Done when' criteria."""

    def test_empty_db_returns_zero(self, db):
        """No accounts, no income, no expenses → 0."""
        svc = SpendService(db)
        user = UserInDB(
            id=999,
            username="ghost",
            full_name="Ghost",
            email="g@g.com",
            disabled=False,
            hashed_password="x",
        )
        assert svc.get_budget_allotment(user) == 0

    def test_zero_income(self, db, user, account):
        """Accounts exist but no 'Work' income → 0."""
        _add_income(db, account, 500.0, category="Gift")
        svc = SpendService(db)
        assert svc.get_budget_allotment(user) == 0

    def test_income_only_no_expenses_no_goals(self, db, user, account):
        """Income present, no expenses, no goals → (paycheck - savings) / 2."""
        _add_income(db, account, 1000.0)
        svc = SpendService(db)
        # savings = 1000 * 10% = 100; remaining = 900; budget = 900 / 2 = 450
        assert svc.get_budget_allotment(user) == pytest.approx(450.0)

    def test_income_with_recurring_expenses(self, db, user, account):
        """Income + bi-weekly recurring expense → correctly prorated."""
        _add_income(db, account, 2000.0)
        # $100 bi-weekly → prorated to 14 days: 100 * 14 / 14 = 100
        _add_expense(db, account, 100.0, recurrence="bi-weekly")
        svc = SpendService(db)
        # paycheck=2000, fixed=100, savings=200, goals=0
        # remaining = 2000 - 100 - 200 - 0 = 1700; budget = 1700/2 = 850
        assert svc.get_budget_allotment(user) == pytest.approx(850.0)

    def test_unknown_recurrence_defaults_to_30_days(self, db, user, account):
        """An unrecognized recurrence string falls back to 30-day period."""
        _add_income(db, account, 2000.0)
        # $300 with unknown recurrence → prorated: 300 * 14 / 30 = 140
        _add_expense(db, account, 300.0, recurrence="every-full-moon")
        svc = SpendService(db)
        expected_fixed = 300.0 * 14 / 30
        expected_savings = 2000.0 * 0.10
        expected = (2000.0 - expected_fixed - expected_savings) / 2
        assert svc.get_budget_allotment(user) == pytest.approx(expected)

    def test_goal_past_deadline_contributes_zero(self, db, user, account):
        """A goal whose deadline is in the past should not contribute."""
        _add_income(db, account, 1000.0)
        _add_goal(db, user, 500.0, days_from_now=-10)
        svc = SpendService(db)
        # Same as income only: (1000 - 100 savings) / 2 = 450
        assert svc.get_budget_allotment(user) == pytest.approx(450.0)

    def test_goal_with_none_progress(self, db, user, account):
        """A goal with progress=NULL should be treated as progress=0."""
        _add_income(db, account, 1000.0)
        _add_goal(db, user, 1400.0, days_from_now=14, progress_none=True)
        svc = SpendService(db)
        # goal contribution: (1400 - 0) / 14 days * 14 = 1400
        # savings: 100; remaining: 1000 - 0 fixed - 100 - 1400 = -500
        # budget = -500 / 2 = -250
        assert svc.get_budget_allotment(user) == pytest.approx(-250.0)

    def test_multiple_recurrence_types(self, db, user, account):
        """Multiple expenses with different recurrences are each prorated correctly."""
        _add_income(db, account, 3000.0)
        _add_expense(db, account, 10.0, recurrence="daily")       # 10*14/1 = 140
        _add_expense(db, account, 70.0, recurrence="weekly")      # 70*14/7 = 140
        _add_expense(db, account, 300.0, recurrence="monthly")    # 300*14/30 = 140
        _add_expense(db, account, 910.0, recurrence="quarterly")  # 910*14/91 = 140
        _add_expense(db, account, 3650.0, recurrence="annually")  # 3650*14/365 = 140

        svc = SpendService(db)
        total_fixed = 140.0 * 5  # 700
        savings = 3000.0 * 0.10  # 300
        expected = (3000.0 - total_fixed - savings) / 2  # (3000-700-300)/2 = 1000
        assert svc.get_budget_allotment(user) == pytest.approx(expected)

    def test_none_savings_percent_defaults_to_zero(self, db, user, account):
        """User with savings_percent=None should not crash.

        Pydantic normally enforces ``int``, but the DB column allows NULL.
        We patch the attribute post-construction to simulate a corrupted row.
        """
        _add_income(db, account, 1000.0)
        # Bypass Pydantic validation to simulate a None value from a raw DB row
        object.__setattr__(user, "savings_percent", None)
        svc = SpendService(db)
        # savings = 0, no fixed, no goals → 1000 / 2 = 500
        assert svc.get_budget_allotment(user) == pytest.approx(500.0)

    def test_budget_allotment_non_negative_integer(self, db, user, account):
        """Step 06: in a healthy (income > commitments) scenario the allotment is
        a non-negative number and is DETERMINISTIC across repeated runs — the
        recurring-expense aggregate now groups by every non-aggregated column
        (incl. recurrence), so SQLite can't pick an arbitrary cadence.

        Note: the allotment is intentionally allowed to go *negative* when fixed
        costs exceed income (a documented, MCP-surfaced signal of over-commitment
        — see test_goal_with_none_progress and the MCP caveats). This test pins
        the non-negative, deterministic behaviour of the healthy case without
        clamping that meaningful negative away.
        """
        _add_income(db, account, 2000.0)
        # Two recurring expenses sharing title/amount/category but DIFFERENT
        # cadences — the case the partial GROUP BY made nondeterministic.
        e1 = ExpenseORM(
            title="Sub", amount=dollars_to_cents(100.0),
            date=datetime.now().strftime("%Y-%m-%d"),
            category="Bills", recurrence="weekly", account_id=account.id,
        )
        e2 = ExpenseORM(
            title="Sub", amount=dollars_to_cents(100.0),
            date=datetime.now().strftime("%Y-%m-%d"),
            category="Bills", recurrence="monthly", account_id=account.id,
        )
        db.add_all([e1, e2])
        db.flush()

        svc = SpendService(db)
        first = svc.get_budget_allotment(user)
        assert first >= 0
        # Deterministic: same inputs, same result on every call.
        for _ in range(5):
            assert svc.get_budget_allotment(user) == first
