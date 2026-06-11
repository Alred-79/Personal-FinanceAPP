"""Shared read-query layer for financial data access.

Both the LangChain assistant tools and the future MCP vault call into these
functions. Each function returns structured data (lists / dicts); callers are
responsible for converting empty results to user-facing strings.

All money values are returned as dollar floats (cents→dollars conversion is
applied here so the boundary stays in one place).
"""

from datetime import date, timedelta

from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session

from ..db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from ..models import UserInDB
from ..money import cents_to_dollars
from ..services.categorization_service import (
    CANONICAL_CATEGORIES,
    canonicalize_category,
)
from ..services.spend_service import SpendService

# Pagination defaults for transaction reads. Bounds the payload so a multi-year
# range can't exceed MCP message-size limits. ``limit`` is clamped to MAX_TX_LIMIT.
DEFAULT_TX_LIMIT = 200
MAX_TX_LIMIT = 500


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_TX_LIMIT)


def _paginated_transactions(
    db: Session,
    *,
    expense_where: list,
    income_where: list,
    limit: int,
    offset: int,
) -> dict:
    """Return a bounded, ordered (date DESC) page of expenses + income combined.

    Expenses and income are merged via UNION ALL at the SQL level so ``limit`` /
    ``offset`` bound the work in the database, not just the response. Returns
    ``{"items": [...], "has_more": bool, "next_offset": int | None}``.
    """
    limit = _clamp_limit(limit)
    offset = max(offset, 0)

    expense_sel = (
        select(
            ExpenseORM.id.label("id"),
            ExpenseORM.title.label("title"),
            ExpenseORM.amount.label("amount"),
            ExpenseORM.date.label("date"),
            ExpenseORM.category.label("category"),
            ExpenseORM.recurrence.label("recurrence"),
            ExpenseORM.account_id.label("account_id"),
            literal("expense").label("type"),
        )
        .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
        .where(*expense_where)
    )
    income_sel = (
        select(
            IncomeORM.id.label("id"),
            IncomeORM.title.label("title"),
            IncomeORM.amount.label("amount"),
            IncomeORM.date.label("date"),
            IncomeORM.category.label("category"),
            literal(None).label("recurrence"),
            IncomeORM.account_id.label("account_id"),
            literal("income").label("type"),
        )
        .join(AccountORM, IncomeORM.account_id == AccountORM.id)
        .where(*income_where)
    )

    # Fetch one extra row to detect whether a further page exists.
    unioned = expense_sel.union_all(income_sel).subquery()
    rows = db.execute(
        select(unioned)
        .order_by(unioned.c.date.desc(), unioned.c.id.desc())
        .limit(limit + 1)
        .offset(offset)
    ).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "id": r.id,
            "title": r.title,
            "amount": cents_to_dollars(r.amount),
            "date": r.date,
            "category": r.category,
            "recurrence": r.recurrence,
            "account_id": r.account_id,
            "type": r.type,
        }
        for r in rows
    ]
    return {
        "items": items,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }


def query_transactions_by_date_range(
    db: Session,
    user_id: int,
    start: str,
    end: str,
    limit: int = DEFAULT_TX_LIMIT,
    offset: int = 0,
) -> dict:
    """Return a paginated page of user-owned transactions between *start* and *end*.

    Dates are validated by the caller (the MCP vault); this assumes well-formed
    ``YYYY-MM-DD`` bounds with ``start <= end``.
    """
    return _paginated_transactions(
        db,
        expense_where=[
            ExpenseORM.date.between(start, end),
            AccountORM.user_id == user_id,
        ],
        income_where=[
            IncomeORM.date.between(start, end),
            AccountORM.user_id == user_id,
        ],
        limit=limit,
        offset=offset,
    )


def query_transactions_by_category(
    db: Session,
    user_id: int,
    category: str,
    limit: int = DEFAULT_TX_LIMIT,
    offset: int = 0,
) -> dict:
    """Return a paginated page of user-owned transactions matching *category*.

    The caller's category is canonicalized (``canonicalize_category``) and matched
    case-insensitively, so ``"food"`` and ``"Food and Drink"`` both resolve to the
    canonical label stored on write.
    """
    canonical = canonicalize_category(category)
    target = canonical.lower()
    return _paginated_transactions(
        db,
        expense_where=[
            func.lower(ExpenseORM.category) == target,
            AccountORM.user_id == user_id,
        ],
        income_where=[
            func.lower(IncomeORM.category) == target,
            AccountORM.user_id == user_id,
        ],
        limit=limit,
        offset=offset,
    )


def query_categories(db: Session, user_id: int) -> dict:
    """Return the canonical category taxonomy plus categories present for the user.

    Lets a consumer discover valid ``get_transactions_by_category`` inputs instead
    of guessing. ``present`` is the distinct set actually used across the user's
    expenses and income.
    """
    expense_cats = (
        db.execute(
            select(ExpenseORM.category)
            .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
            .where(AccountORM.user_id == user_id)
            .distinct()
        )
        .scalars()
        .all()
    )
    income_cats = (
        db.execute(
            select(IncomeORM.category)
            .join(AccountORM, IncomeORM.account_id == AccountORM.id)
            .where(AccountORM.user_id == user_id)
            .distinct()
        )
        .scalars()
        .all()
    )
    present = sorted({c for c in (*expense_cats, *income_cats) if c})
    return {
        "canonical": list(CANONICAL_CATEGORIES),
        "present": present,
    }


def query_accounts(db: Session, user_id: int) -> list[dict]:
    """Return all accounts belonging to *user_id*."""
    accounts = (
        db.execute(select(AccountORM).where(AccountORM.user_id == user_id))
        .scalars()
        .all()
    )
    return [
        {
            "id": a.id,
            "name": a.name,
            "type": a.type,
            "balance": cents_to_dollars(a.balance),
            "last_updated": str(a.last_updated),
            "user_id": a.user_id,
        }
        for a in accounts
    ]


def query_transactions_per_account(
    db: Session,
    user_id: int,
    account_id: int,
    limit: int = DEFAULT_TX_LIMIT,
    offset: int = 0,
) -> dict | None:
    """Return a paginated page of transactions for *account_id* after ownership check.

    Returns ``None`` when *account_id* does not belong to *user_id* (ownership
    rejection, not an empty result). Otherwise returns the standard paginated
    ``{"items", "has_more", "next_offset"}`` payload.
    """
    account_check = db.execute(
        select(AccountORM.id).where(
            AccountORM.id == account_id,
            AccountORM.user_id == user_id,
        )
    ).first()
    if not account_check:
        return None

    # Ownership already verified above; the join still scopes to user_id defensively.
    return _paginated_transactions(
        db,
        expense_where=[
            ExpenseORM.account_id == account_id,
            AccountORM.user_id == user_id,
        ],
        income_where=[
            IncomeORM.account_id == account_id,
            AccountORM.user_id == user_id,
        ],
        limit=limit,
        offset=offset,
    )


def query_goals(db: Session, user_id: int) -> list[dict]:
    """Return all financial goals belonging to *user_id*."""
    goals = (
        db.execute(select(GoalORM).where(GoalORM.user_id == user_id))
        .scalars()
        .all()
    )
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "amount": cents_to_dollars(g.amount),
            "date": g.date,
            "completed": bool(g.completed),
            "progress": cents_to_dollars(g.progress),
        }
        for g in goals
    ]


def query_user(db: Session, user_id: int) -> UserInDB | None:
    """Fetch the user as a Pydantic UserInDB for service calls that need user settings."""
    row = db.execute(select(UserORM).where(UserORM.id == user_id)).scalar_one_or_none()
    if row is None:
        return None
    return UserInDB(
        id=row.id,
        username=row.username,
        email=row.email,
        full_name=row.full_name,
        disabled=bool(row.disabled),
        hashed_password=row.hashed_password,
        spend_warning=row.spend_warning,
        savings_percent=row.savings_percent,
    )


def query_spend_summary(db: Session, user_id: int) -> dict:
    """Return weekly budget allotment and spend for *user_id*."""
    user = UserInDB(
        id=user_id,
        username="",
        email="",
        full_name="",
        disabled=False,
        hashed_password="",
    )
    spend_service = SpendService(db)
    # The allotment silently returns 0 when there is no 'Work'-categorized income;
    # surface that explicitly so a consumer can tell a real $0 budget from "no
    # income on record".
    has_work_income = (
        db.execute(
            select(IncomeORM.id)
            .join(AccountORM, IncomeORM.account_id == AccountORM.id)
            .where(
                AccountORM.user_id == user_id,
                func.lower(IncomeORM.category) == "work",
            )
            .limit(1)
        ).first()
        is not None
    )
    return {
        "weekly_max_budget": spend_service.get_budget_allotment(user),
        "weekly_spend": spend_service.get_spend_over_time(
            user,
            date.today() - timedelta(days=6),
            date.today() + timedelta(days=1),
        ),
        "has_work_income": has_work_income,
    }
