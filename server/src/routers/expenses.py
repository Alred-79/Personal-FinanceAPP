"""Expenses router. A thin wrapper over TransactionService.

The logic that moves balances lives in ``TransactionService``. This module just
wires up the route paths, the Pydantic request schema, and ``balance_sign=-1``
(expenses subtract from account balances).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.models import Expense, UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.transaction_service import TransactionService
from server.src.db.session import get_db
from server.src.db.models import Expense as ExpenseORM

router = APIRouter(prefix="/expenses", tags=["expenses"])

SIGN = -1  # expenses subtract from account balance


def _svc(db: Session) -> TransactionService:
    return TransactionService(db)


@router.get("/")
async def get_expenses(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).list_all(current_user.id, ExpenseORM)


@router.get("/fixed-per-month/")
async def get_fixed_per_month(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).fixed_per_month(current_user.id)


@router.get("/{id}/")
async def get_expense(
    id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).get_one(id, current_user.id, ExpenseORM)


@router.post("/")
async def create_expense(
    expense: Expense,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).create(
        current_user.id,
        ExpenseORM,
        SIGN,
        title=expense.title,
        amount=expense.amount,
        tx_date=expense.date,
        category=expense.category,
        account_id=expense.account_id,
        extra_fields={"recurrence": expense.recurrence},
    )


@router.put("/{id}/")
async def update_expense(
    id: int,
    expense: Expense,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).update(
        id,
        current_user.id,
        ExpenseORM,
        SIGN,
        title=expense.title,
        amount=expense.amount,
        tx_date=expense.date,
        category=expense.category,
        account_id=expense.account_id,
        extra_fields={"recurrence": expense.recurrence},
    )


@router.delete("/{id}/")
async def delete_expense(
    id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).delete(id, current_user.id, ExpenseORM, SIGN)
