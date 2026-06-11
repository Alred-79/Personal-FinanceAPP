"""Transactions router. Uses the ORM and stores money as integer cents.

Returns a paginated, filtered list of the current user's income and expense
transactions, newest first. Amounts go from cents to dollars for the response.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
)
from server.src.money import cents_to_dollars, dollars_to_cents

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
        conditions.append(model.date <= date_to)
    if amount_min is not None:
        conditions.append(model.amount >= dollars_to_cents(amount_min))
    if amount_max is not None:
        conditions.append(model.amount <= dollars_to_cents(amount_max))
    return conditions


def _row_to_dict(row, tx_type: str) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "amount": cents_to_dollars(row.amount),
        "date": row.date,
        "category": row.category,
        "type": tx_type,
    }


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

    income_rows = (
        db.execute(
            select(IncomeORM).where(and_(*_apply_filters(IncomeORM, **filter_args)))
        )
        .scalars()
        .all()
    )
    expense_rows = (
        db.execute(
            select(ExpenseORM).where(and_(*_apply_filters(ExpenseORM, **filter_args)))
        )
        .scalars()
        .all()
    )

    # Merge both lists, sort, then slice so pagination spans both tables
    items = [_row_to_dict(r, "income") for r in income_rows]
    items += [_row_to_dict(r, "expense") for r in expense_rows]
    items.sort(key=lambda t: t["date"], reverse=True)

    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset : offset + page_size]

    return {"items": page_items, "total": total, "page": page, "page_size": page_size}
