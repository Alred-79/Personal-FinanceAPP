"""Transactions router. Uses the ORM and stores money as integer cents.

Returns a paginated, filtered list of the current user's income and expense
transactions, newest first. Amounts go from cents to dollars for the response.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.read_queries import paginated_transactions_page
from server.src.db.session import get_db
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
)
from server.src.money import dollars_to_cents

router = APIRouter(prefix="/transactions", tags=["transactions"])

_MAX_PAGE_SIZE = 100


def _apply_filters(model, account_ids, q, category, date_from, date_to, amount_min, amount_max):
    conditions = [model.account_id.in_(account_ids)]
    if q:
        conditions.append(
            or_(model.title.ilike(f"%{q}%"), model.category.ilike(f"%{q}%"))
        )
    if category:
        conditions.append(model.category == category)
    if date_from:
        conditions.append(model.date >= date_from)
    if date_to:
        # HOUSE RULE: ranges are conceptually half-open ``[start, nextday)``.
        # ``date`` is a date-only ISO string, so inclusive ``<= date_to`` is
        # equivalent (includes the whole end day); a future time-bearing column
        # must switch to the half-open ``< (date_to + 1 day)`` form.
        conditions.append(model.date <= date_to)
    if amount_min is not None:
        conditions.append(model.amount >= dollars_to_cents(amount_min))
    if amount_max is not None:
        conditions.append(model.amount <= dollars_to_cents(amount_max))
    return conditions


@router.get("/")
async def get_all_transactions(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
    q: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    account_id: Optional[int] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=_MAX_PAGE_SIZE),
):
    # Resolve which account IDs to query
    if account_id is not None:
        owned = db.execute(
            select(AccountORM.id).where(
                AccountORM.id == account_id,
                AccountORM.user_id == current_user.id,
            )
        ).scalar_one_or_none()
        if owned is None:
            raise HTTPException(status_code=404, detail="Account not found")
        account_ids = [account_id]
    else:
        account_ids = (
            db.execute(
                select(AccountORM.id).where(AccountORM.user_id == current_user.id)
            )
            .scalars()
            .all()
        )

    if not account_ids:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    filter_args = dict(
        account_ids=account_ids,
        q=q,
        category=category,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
    )

    # SQL-side pagination: a single UNION ALL with LIMIT/OFFSET for the page plus
    # a COUNT for ``total`` — no more loading every income+expense row into Python
    # to merge/sort/slice. The same ``_apply_filters`` conditions are applied to
    # each leg, so ``q`` / category / date / amount filters all still bite, and
    # ownership is scoped via ``account_id.in_(account_ids)``. The response shape
    # ``{items, total, page, page_size}`` is unchanged, so the client is
    # unaffected.
    return paginated_transactions_page(
        db,
        expense_where=_apply_filters(ExpenseORM, **filter_args),
        income_where=_apply_filters(IncomeORM, **filter_args),
        page=page,
        page_size=page_size,
    )
