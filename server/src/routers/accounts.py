"""Accounts router. Uses the ORM and stores money as integer cents.

Every endpoint uses the request scoped ``get_db`` session. The ``delete_account``
endpoint leans on the ORM cascade (``delete-orphan``) plus the automatic commit
and rollback in ``get_db`` to stay atomic, so there's no manual
``BEGIN TRANSACTION`` or ``COMMIT`` anywhere.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.models import Account as AccountSchema, UserInDB
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Token as TokenORM,
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


class TransferIn(BaseModel):
    """A real intra-app transfer between two manually-managed accounts (v2)."""

    from_account_id: int
    to_account_id: int
    amount: float = Field(gt=0, allow_inf_nan=False, le=1_000_000_000_000)
    note: str = Field(default="", max_length=200)


def _is_plaid_managed(
    db: Session,
    user_id: int,
    account_name: str,
    *,
    plaid_account_id: str | None = None,
) -> bool:
    """Whether an account is Plaid-synced (Step 08: id-keyed, name fallback).

    Step 08 de-name-keys Plaid: an account created by the exchange flow carries
    its ``plaid_account_id``, and THAT — not a shared name — is the durable link.
    So the primary check is ``plaid_account_id IS NOT NULL``, which survives a
    rename (the old name-keyed guard would have silently mis-classified a renamed
    Plaid account as manual and let a transfer double-count on the next sync).

    A name-match against a ``Token`` row is kept as a FALLBACK so a pre-Step-08
    (un-migrated) link — and the existing test corpus that seeds a Token with a
    matching name but no ``plaid_account_id`` — is still classified as managed.
    Pass ``plaid_account_id`` from the account row to get the id-keyed check.
    """
    if plaid_account_id is not None:
        return True
    return (
        db.execute(
            select(TokenORM.id).where(
                TokenORM.user_id == user_id, TokenORM.name == account_name
            )
        ).scalar_one_or_none()
        is not None
    )


@router.post("/transfer/")
async def transfer_between_accounts(
    payload: TransferIn,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Move money between two of the user's **manually-managed** accounts.

    Plaid-synced accounts are refused: the next sync would overwrite the local
    balance and silently undo the transfer. External transfers stay out
    entirely (money-transmission territory). Both legs move in one DB
    transaction (``get_db`` commits/rolls back the whole request).
    """
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(status_code=422, detail="Cannot transfer to the same account")

    accounts = {}
    for label, account_id in (
        ("from", payload.from_account_id),
        ("to", payload.to_account_id),
    ):
        row = db.execute(
            select(AccountORM).where(
                AccountORM.id == account_id,
                AccountORM.user_id == current_user.id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Account ({label}) not found")
        # ── Plaid guard (Step 06 → Step 08: id-keyed) ────────────────────────
        # Plaid-synced accounts are refused: the next sync would overwrite the
        # local balance and silently undo the transfer. Step 08 de-name-keyed
        # this onto ``Account.plaid_account_id`` (passed below), so a *renamed*
        # Plaid account is still correctly refused; the name→Token fallback in
        # ``_is_plaid_managed`` keeps un-migrated links classified too.
        if _is_plaid_managed(
            db, current_user.id, row.name, plaid_account_id=row.plaid_account_id
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"“{row.name}” is synced from your bank; transfers are only "
                    "supported between manually-managed accounts."
                ),
            )
        accounts[label] = row

    amount_cents = dollars_to_cents(payload.amount)
    from_id = payload.from_account_id
    to_id = payload.to_account_id

    # ── Debit leg: guarded conditional UPDATE (no TOCTOU) ────────────────────
    # The insufficient-funds check and the decrement are a single statement: the
    # WHERE clause carries the ``balance >= amount`` guard, so two concurrent
    # transfers can't both pass a stale check and overdraw. rowcount == 0 means
    # the guard failed (insufficient funds); nothing moved.
    debit = db.execute(
        update(AccountORM)
        .where(
            AccountORM.id == from_id,
            AccountORM.user_id == current_user.id,
            AccountORM.balance >= amount_cents,
        )
        .values(
            balance=AccountORM.balance - amount_cents,
            last_updated=func.current_timestamp(),
        )
    )
    if debit.rowcount == 0:
        raise HTTPException(status_code=422, detail="Insufficient balance")

    # ── Credit leg: issued atomic UPDATE ─────────────────────────────────────
    db.execute(
        update(AccountORM)
        .where(AccountORM.id == to_id, AccountORM.user_id == current_user.id)
        .values(
            balance=AccountORM.balance + amount_cents,
            last_updated=func.current_timestamp(),
        )
    )

    # ── Ledger record + note ─────────────────────────────────────────────────
    # Two linked rows under category "Transfer": an Expense on the source and an
    # Income on the destination, both carrying the user's note. Chosen over a
    # dedicated transfer table because it keeps every existing ledger view (the
    # transactions list, per-account history) correct with no schema change, and
    # the two rows net to zero across the user's accounts. "Transfer" is not a
    # budget category, so per-category budget summaries are unaffected. The note
    # the user typed is now persisted (it was validated then dropped before).
    today = date.today().isoformat()
    note = payload.note or ""
    db.add(
        ExpenseORM(
            title=note or "Transfer out",
            amount=amount_cents,
            date=today,
            category="Transfer",
            recurrence=None,
            account_id=from_id,
        )
    )
    db.add(
        IncomeORM(
            title=note or "Transfer in",
            amount=amount_cents,
            date=today,
            category="Transfer",
            account_id=to_id,
        )
    )

    db.flush()

    # Reload the two accounts so the response reflects the server-side balances
    # produced by the issued UPDATEs (the loaded ORM copies are now stale).
    db.expire(accounts["from"])
    db.expire(accounts["to"])

    return {
        "message": "Transfer completed",
        "from": _account_to_dict(accounts["from"]),
        "to": _account_to_dict(accounts["to"]),
        "note": note,
    }


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
