"""Income router. A thin wrapper over TransactionService.

The logic that moves balances lives in ``TransactionService``. This module just
wires up the route paths, the Pydantic request schema, and ``balance_sign=+1``
(income adds to account balances).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.models import Income, UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.transaction_service import TransactionService
from server.src.db.session import get_db
from server.src.db.models import Income as IncomeORM

router = APIRouter(prefix="/income", tags=["income"])

SIGN = +1  # income adds to account balance


def _svc(db: Session) -> TransactionService:
    return TransactionService(db)


@router.get("/")
async def get_all_income(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).list_all(current_user.id, IncomeORM)


@router.get("/{id}/")
async def get_income(
    id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).get_one(id, current_user.id, IncomeORM)


@router.post("/")
async def create_income(
    income: Income,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).create(
        current_user.id,
        IncomeORM,
        SIGN,
        title=income.title,
        amount=income.amount,
        tx_date=income.date,
        category=income.category,
        account_id=income.account_id,
        extra_fields={"recurrence": income.recurrence},
    )


@router.put("/{id}/")
async def update_income(
    id: int,
    income: Income,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).update(
        id,
        current_user.id,
        IncomeORM,
        SIGN,
        title=income.title,
        amount=income.amount,
        tx_date=income.date,
        category=income.category,
        account_id=income.account_id,
        extra_fields={"recurrence": income.recurrence},
    )


@router.delete("/{id}/")
async def delete_income(
    id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return _svc(db).delete(id, current_user.id, IncomeORM, SIGN)
