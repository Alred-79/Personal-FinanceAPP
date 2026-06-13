"""Tests for the shared read-query layer (read_queries.py).

Covers:
- Correct rows and dollar amounts for each function.
- Empty-case behavior.
- query_transactions_per_account cross-user ownership rejection.
- Date-range and category filters return only matching, user-owned rows.
- Inverted date range returns empty (no error).
- Unicode / odd titles pass through unchanged.
- cents→dollars conversion accuracy.
- No-pagination v1 limitation: all rows returned.
"""

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.services.read_queries import (
    query_accounts,
    query_goals,
    query_spend_summary,
    query_transactions_by_category,
    query_transactions_by_date_range,
    query_transactions_per_account,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_user(db, username="alice", email="alice@example.com"):
    user = UserORM(
        username=username,
        full_name="Alice",
        email=email,
        hashed_password="x",
        disabled=0,
    )
    db.add(user)
    db.flush()
    return user


def _make_account(db, user_id, name="Checking", balance_cents=100_00):
    acct = AccountORM(name=name, type="checking", balance=balance_cents, user_id=user_id)
    db.add(acct)
    db.flush()
    return acct


def _make_expense(db, account_id, title="Coffee", amount_cents=5_00,
                  date="2024-03-15", category="Food", recurrence=None):
    exp = ExpenseORM(
        title=title,
        amount=amount_cents,
        date=date,
        category=category,
        recurrence=recurrence,
        account_id=account_id,
    )
    db.add(exp)
    db.flush()
    return exp


def _make_income(db, account_id, title="Salary", amount_cents=200_00,
                 date="2024-03-01", category="Work"):
    inc = IncomeORM(
        title=title,
        amount=amount_cents,
        date=date,
        category=category,
        account_id=account_id,
    )
    db.add(inc)
    db.flush()
    return inc


def _make_goal(db, user_id, name="Vacation", amount_cents=1000_00,
               date="2025-12-31", progress_cents=100_00, completed=0):
    goal = GoalORM(
        name=name,
        description="Beach trip",
        amount=amount_cents,
        date=date,
        user_id=user_id,
        completed=completed,
        progress=progress_cents,
    )
    db.add(goal)
    db.flush()
    return goal


# ---------------------------------------------------------------------------
# query_transactions_by_date_range
# ---------------------------------------------------------------------------

class TestQueryTransactionsByDateRange:
    def test_returns_expense_in_range(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, amount_cents=10_99, date="2024-03-10")
        result = query_transactions_by_date_range(db_session, user.id, "2024-03-01", "2024-03-31")["items"]
        assert len(result) == 1
        assert result[0]["amount"] == 10.99
        assert result[0]["type"] == "expense"

    def test_returns_income_in_range(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_income(db_session, acct.id, amount_cents=500_00, date="2024-03-15")
        result = query_transactions_by_date_range(db_session, user.id, "2024-03-01", "2024-03-31")["items"]
        assert len(result) == 1
        assert result[0]["amount"] == 500.00
        assert result[0]["type"] == "income"
        assert result[0]["recurrence"] is None

    def test_excludes_out_of_range(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, date="2024-02-28")
        result = query_transactions_by_date_range(db_session, user.id, "2024-03-01", "2024-03-31")["items"]
        assert result == []

    def test_inverted_range_returns_empty(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, date="2024-03-10")
        result = query_transactions_by_date_range(db_session, user.id, "2024-03-31", "2024-03-01")["items"]
        assert result == []

    def test_only_returns_own_user_rows(self, db_session):
        alice = _make_user(db_session, "alice", "alice@x.com")
        bob = _make_user(db_session, "bob", "bob@x.com")
        acct_a = _make_account(db_session, alice.id)
        acct_b = _make_account(db_session, bob.id)
        _make_expense(db_session, acct_a.id, title="Alice expense", date="2024-03-10")
        _make_expense(db_session, acct_b.id, title="Bob expense", date="2024-03-10")
        result = query_transactions_by_date_range(db_session, alice.id, "2024-03-01", "2024-03-31")["items"]
        assert len(result) == 1
        assert result[0]["title"] == "Alice expense"

    def test_both_expense_and_income_returned(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, date="2024-03-10")
        _make_income(db_session, acct.id, date="2024-03-10")
        result = query_transactions_by_date_range(db_session, user.id, "2024-03-01", "2024-03-31")["items"]
        types = {r["type"] for r in result}
        assert types == {"expense", "income"}

    def test_dollars_conversion_exact(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, amount_cents=1099, date="2024-03-10")
        result = query_transactions_by_date_range(db_session, user.id, "2024-03-01", "2024-03-31")["items"]
        assert result[0]["amount"] == 10.99

    def test_unicode_title_passes_through(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, title="Café ☕ résumé", date="2024-03-10")
        result = query_transactions_by_date_range(db_session, user.id, "2024-03-01", "2024-03-31")["items"]
        assert result[0]["title"] == "Café ☕ résumé"

    def test_empty_db_returns_empty_list(self, db_session):
        user = _make_user(db_session)
        result = query_transactions_by_date_range(db_session, user.id, "2024-01-01", "2024-12-31")["items"]
        assert result == []


# ---------------------------------------------------------------------------
# query_transactions_by_category
# ---------------------------------------------------------------------------

class TestQueryTransactionsByCategory:
    def test_returns_matching_expense(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, category="Food", amount_cents=8_50)
        result = query_transactions_by_category(db_session, user.id, "Food")["items"]
        assert len(result) == 1
        assert result[0]["amount"] == 8.50
        assert result[0]["category"] == "Food"
        assert result[0]["type"] == "expense"

    def test_returns_matching_income(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_income(db_session, acct.id, category="Work", amount_cents=300_00)
        result = query_transactions_by_category(db_session, user.id, "Work")["items"]
        assert len(result) == 1
        assert result[0]["amount"] == 300.00
        assert result[0]["type"] == "income"

    def test_excludes_other_category(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, category="Transport")
        result = query_transactions_by_category(db_session, user.id, "Food")["items"]
        assert result == []

    def test_only_returns_own_user_rows(self, db_session):
        alice = _make_user(db_session, "alice", "alice@x.com")
        bob = _make_user(db_session, "bob", "bob@x.com")
        acct_a = _make_account(db_session, alice.id)
        acct_b = _make_account(db_session, bob.id)
        _make_expense(db_session, acct_a.id, category="Food", title="Alice food")
        _make_expense(db_session, acct_b.id, category="Food", title="Bob food")
        result = query_transactions_by_category(db_session, alice.id, "Food")["items"]
        assert len(result) == 1
        assert result[0]["title"] == "Alice food"

    def test_includes_account_id_field(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, category="Food")
        result = query_transactions_by_category(db_session, user.id, "Food")["items"]
        assert "account_id" in result[0]
        assert result[0]["account_id"] == acct.id

    def test_expense_income_id_spaces_preserved(self, db_session):
        """Expense and income rows with the same db id are both returned."""
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, category="Work")
        _make_income(db_session, acct.id, category="Work")
        result = query_transactions_by_category(db_session, user.id, "Work")["items"]
        types = {r["type"] for r in result}
        assert types == {"expense", "income"}

    def test_empty_returns_empty_list(self, db_session):
        user = _make_user(db_session)
        result = query_transactions_by_category(db_session, user.id, "Food")["items"]
        assert result == []


# ---------------------------------------------------------------------------
# query_accounts
# ---------------------------------------------------------------------------

class TestQueryAccounts:
    def test_returns_accounts(self, db_session):
        user = _make_user(db_session)
        _make_account(db_session, user.id, name="Checking", balance_cents=150_00)
        result = query_accounts(db_session, user.id)
        assert len(result) == 1
        assert result[0]["name"] == "Checking"
        assert result[0]["balance"] == 150.00

    def test_balance_dollar_conversion(self, db_session):
        user = _make_user(db_session)
        _make_account(db_session, user.id, balance_cents=12345)
        result = query_accounts(db_session, user.id)
        assert result[0]["balance"] == 123.45

    def test_only_returns_own_accounts(self, db_session):
        alice = _make_user(db_session, "alice", "alice@x.com")
        bob = _make_user(db_session, "bob", "bob@x.com")
        _make_account(db_session, alice.id, name="Alice Checking")
        _make_account(db_session, bob.id, name="Bob Savings")
        result = query_accounts(db_session, alice.id)
        assert len(result) == 1
        assert result[0]["name"] == "Alice Checking"

    def test_empty_returns_empty_list(self, db_session):
        user = _make_user(db_session)
        result = query_accounts(db_session, user.id)
        assert result == []

    def test_includes_required_fields(self, db_session):
        user = _make_user(db_session)
        _make_account(db_session, user.id)
        result = query_accounts(db_session, user.id)
        for field in ("id", "name", "type", "balance", "last_updated", "user_id"):
            assert field in result[0]


# ---------------------------------------------------------------------------
# query_transactions_per_account
# ---------------------------------------------------------------------------

class TestQueryTransactionsPerAccount:
    def test_returns_transactions_for_owned_account(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, amount_cents=2_50)
        result = query_transactions_per_account(db_session, user.id, acct.id)
        assert result is not None
        assert len(result["items"]) == 1
        assert result["items"][0]["amount"] == 2.50

    def test_cross_user_rejected_returns_none(self, db_session):
        alice = _make_user(db_session, "alice", "alice@x.com")
        bob = _make_user(db_session, "bob", "bob@x.com")
        bob_acct = _make_account(db_session, bob.id)
        _make_expense(db_session, bob_acct.id)
        result = query_transactions_per_account(db_session, alice.id, bob_acct.id)
        assert result is None

    def test_nonexistent_account_returns_none(self, db_session):
        user = _make_user(db_session)
        result = query_transactions_per_account(db_session, user.id, 9999)
        assert result is None

    def test_owned_empty_account_returns_empty_list(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        result = query_transactions_per_account(db_session, user.id, acct.id)
        assert result is not None
        assert result["items"] == []

    def test_returns_both_expense_and_income(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id)
        _make_income(db_session, acct.id)
        result = query_transactions_per_account(db_session, user.id, acct.id)
        assert result is not None
        types = {r["type"] for r in result["items"]}
        assert types == {"expense", "income"}

    def test_does_not_return_other_accounts_rows(self, db_session):
        user = _make_user(db_session)
        acct1 = _make_account(db_session, user.id, name="Checking")
        acct2 = _make_account(db_session, user.id, name="Savings")
        _make_expense(db_session, acct1.id, title="From acct1")
        _make_expense(db_session, acct2.id, title="From acct2")
        result = query_transactions_per_account(db_session, user.id, acct1.id)
        assert result is not None
        assert all(r["title"] == "From acct1" for r in result["items"])

    def test_dollar_conversion_on_per_account(self, db_session):
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        _make_expense(db_session, acct.id, amount_cents=7_77)
        result = query_transactions_per_account(db_session, user.id, acct.id)
        assert result is not None
        assert result["items"][0]["amount"] == 7.77


# ---------------------------------------------------------------------------
# query_goals
# ---------------------------------------------------------------------------

class TestQueryGoals:
    def test_returns_goals(self, db_session):
        user = _make_user(db_session)
        _make_goal(db_session, user.id, amount_cents=500_00, progress_cents=50_00)
        result = query_goals(db_session, user.id)
        assert len(result) == 1
        assert result[0]["amount"] == 500.00
        assert result[0]["progress"] == 50.00

    def test_completed_flag_cast_to_bool(self, db_session):
        user = _make_user(db_session)
        _make_goal(db_session, user.id, completed=1)
        result = query_goals(db_session, user.id)
        assert result[0]["completed"] is True

    def test_incomplete_flag_cast_to_bool(self, db_session):
        user = _make_user(db_session)
        _make_goal(db_session, user.id, completed=0)
        result = query_goals(db_session, user.id)
        assert result[0]["completed"] is False

    def test_only_returns_own_goals(self, db_session):
        alice = _make_user(db_session, "alice", "alice@x.com")
        bob = _make_user(db_session, "bob", "bob@x.com")
        _make_goal(db_session, alice.id, name="Alice goal")
        _make_goal(db_session, bob.id, name="Bob goal")
        result = query_goals(db_session, alice.id)
        assert len(result) == 1
        assert result[0]["name"] == "Alice goal"

    def test_empty_returns_empty_list(self, db_session):
        user = _make_user(db_session)
        result = query_goals(db_session, user.id)
        assert result == []

    def test_includes_required_fields(self, db_session):
        user = _make_user(db_session)
        _make_goal(db_session, user.id)
        result = query_goals(db_session, user.id)
        for field in ("id", "name", "description", "amount", "date", "completed", "progress"):
            assert field in result[0]

    def test_dollar_conversion_exact(self, db_session):
        user = _make_user(db_session)
        _make_goal(db_session, user.id, amount_cents=10_99, progress_cents=5_01)
        result = query_goals(db_session, user.id)
        assert result[0]["amount"] == 10.99
        assert result[0]["progress"] == 5.01


# ---------------------------------------------------------------------------
# query_spend_summary
# ---------------------------------------------------------------------------

class TestQuerySpendSummary:
    def test_returns_expected_keys(self, db_session):
        user = _make_user(db_session)
        result = query_spend_summary(db_session, user.id)
        assert "weekly_max_budget" in result
        assert "weekly_spend" in result

    def test_zero_when_no_data(self, db_session):
        user = _make_user(db_session)
        result = query_spend_summary(db_session, user.id)
        assert result["weekly_max_budget"] == 0
        assert result["weekly_spend"] == 0

    def test_spend_reflects_recent_expenses(self, db_session):
        from datetime import date, timedelta
        user = _make_user(db_session)
        acct = _make_account(db_session, user.id)
        today = date.today().isoformat()
        _make_income(db_session, acct.id, category="Work", amount_cents=200_00, date=today)
        _make_expense(db_session, acct.id, amount_cents=20_00, date=today, recurrence=None)
        result = query_spend_summary(db_session, user.id)
        assert result["weekly_spend"] == 20.00

    def test_spend_summary_uses_real_savings_percent(self, db_session):
        """Step 06: the summary loads the real user row, so a non-default
        ``savings_percent`` is reflected — matching what ``SpendService`` computes
        with the actual user (not a fabricated default-percent user)."""
        from server.src.models import UserInDB
        from server.src.services.spend_service import SpendService

        # Distinctive savings_percent (40), not the model default (10).
        user = _make_user(db_session, username="saver", email="saver@example.com")
        user.savings_percent = 40
        db_session.flush()
        acct = _make_account(db_session, user.id)
        _make_income(db_session, acct.id, category="Work", amount_cents=200_00)

        summary = query_spend_summary(db_session, user.id)

        real_user = UserInDB(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            disabled=False,
            hashed_password="x",
            savings_percent=40,
        )
        expected = SpendService(db_session).get_budget_allotment(real_user)
        assert summary["weekly_max_budget"] == expected

        # And it must differ from what a default-percent (10) user would yield —
        # proving the real percent is actually threaded through.
        default_user = UserInDB(
            id=user.id, username=user.username, email=user.email,
            full_name=user.full_name, disabled=False, hashed_password="x",
            savings_percent=10,
        )
        assert SpendService(db_session).get_budget_allotment(default_user) != expected

    def test_spend_summary_missing_user_raises(self, db_session):
        import pytest

        with pytest.raises(ValueError):
            query_spend_summary(db_session, 999999)
