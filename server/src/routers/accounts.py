"""Accounts router. Uses the ORM and stores money as integer cents.

Every endpoint uses the request scoped ``get_db`` session. The ``delete_account``
endpoint leans on the ORM cascade (``delete-orphan``) plus the automatic commit
and rollback in ``get_db`` to stay atomic, so there's no manual
``BEGIN TRANSACTION`` or ``COMMIT`` anywhere.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.models import Account as AccountSchema, UserInDB
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
)
from server.src.money import dollars_to_cents, cents_to_dollars

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _account_to_dict(account: AccountORM) -> dict:
    """Serialize an ORM Account row to a dict with dollars (not cents)."""
    return {
        "id": account.id,
        "name": account.name,
        "type": account.type,
        "balance": cents_to_dollars(account.balance),
        "last_updated": account.last_updated,
        "user_id": account.user_id,
    }


def _transaction_to_dict(row, tx_type: str) -> dict:
    """Serialize an ORM Expense or Income row to a dict with dollars."""
    return {
        "id": row.id,
        "title": row.title,
        "amount": cents_to_dollars(row.amount),
        "date": row.date,
        "category": row.category,
        "type": tx_type,
    }


@router.get("/")
async def get_accounts(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    accounts = db.execute(
        select(AccountORM).where(AccountORM.user_id == current_user.id)
    ).scalars().all()
    return [_account_to_dict(a) for a in accounts]


@router.get("/{id}/")
async def get_account(
    id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    account = db.execute(
        select(AccountORM).where(
            AccountORM.id == id, AccountORM.user_id == current_user.id
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return _account_to_dict(account)


@router.get("/{id}/transactions/")
async def get_account_transactions(
    id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    account = db.execute(
        select(AccountORM).where(
            AccountORM.id == id, AccountORM.user_id == current_user.id
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    expenses = db.execute(
        select(ExpenseORM).where(ExpenseORM.account_id == id)
    ).scalars().all()
    income = db.execute(
        select(IncomeORM).where(IncomeORM.account_id == id)
    ).scalars().all()

    transactions = [_transaction_to_dict(e, "expense") for e in expenses]
    transactions += [_transaction_to_dict(i, "income") for i in income]
    return transactions


@router.post("/")
async def create_account(
    account: AccountSchema,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    new_account = AccountORM(
        name=account.name,
        type=account.type,
        balance=dollars_to_cents(account.balance),
        user_id=current_user.id,
    )
    db.add(new_account)
    db.flush()
    return {"message": "Account created successfully"}


@router.put("/{id}/")
async def update_account(
    id: int,
    account: AccountSchema,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    existing = db.execute(
        select(AccountORM).where(
            AccountORM.id == id, AccountORM.user_id == current_user.id
        )
    ).scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    existing.name = account.name
    existing.type = account.type
    existing.balance = dollars_to_cents(account.balance)
    return {"message": "Account updated successfully"}


@router.delete("/{id}/")
async def delete_account(
    id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    account = db.execute(
        select(AccountORM).where(
            AccountORM.id == id, AccountORM.user_id == current_user.id
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # The ORM cascade (delete-orphan) takes care of the child expense and income rows.
    # get_db commits on success and rolls back on any exception, so it's atomic.
    db.delete(account)
    db.flush()

    return {"message": "Account and all related transactions deleted successfully"}
