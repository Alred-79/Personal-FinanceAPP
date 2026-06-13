"""Plaid router. Uses the ORM and syncs with a cursor.

Handles creating a Plaid Link token, exchanging the public token, syncing
transactions in a background task, and reading balances. Every database call
goes through the request scoped ORM session.

Sign convention (spelled out in ``plaid_client.py``):
    Plaid ``amount > 0``  → Expense (money leaving the account)
    Plaid ``amount < 0``  → Income  (money entering the account)
"""

import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.databridge.plaid_client import PlaidClient
from server.src.services.plaid_service import PlaidService
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db, SessionLocal
from server.src.db.models import (
    Account as AccountORM,
    Token as TokenORM,
)
from server.src.money import dollars_to_cents
from server.src.models import (
    UserInDB,
    PublicTokenExchangeRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plaid", tags=["plaid"])


# ── Link & token exchange ────────────────────────────────────────────────────


@router.get("/link-token/")
async def get_link_token(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
):
    """Mint a Plaid Link token for the authenticated user (C3).

    Previously this took a caller-supplied ``user_id`` query param with NO auth
    dependency, so anyone on the network could mint Link tokens against the real
    Plaid app for an arbitrary id — burning quota and attaching a Link session
    to a chosen id. The ``client_user_id`` is now derived from the session
    (``str(current_user.id)``, which is stable per user); the ``user_id`` param
    is gone, and FastAPI rejects an unauthenticated request with 401 before any
    Plaid call is made.
    """
    databridge = PlaidClient()
    link_token = databridge.create_link_token(str(current_user.id))
    return {"link_token": link_token}


@router.post("/exchange-public-token/")
async def exchange_public_token(
    token: PublicTokenExchangeRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    databridge = PlaidClient()
    access_token = databridge.exchange_public_token(token.public_token)

    # Store the access token
    new_token = TokenORM(
        user_id=current_user.id,
        name=token.name,
        key=access_token,
    )
    db.add(new_token)
    db.flush()  # assign PK

    # Get plaid account balance and create the local account.
    # Guard against institutions that return zero accounts.
    plaid_accounts = databridge.get_balance(access_token)
    if not plaid_accounts:
        raise HTTPException(
            status_code=400,
            detail="No accounts returned by the linked institution.",
        )

    plaid_account = plaid_accounts[0].to_dict()

    new_account = AccountORM(
        name=token.name,
        type=plaid_account["type"],
        balance=dollars_to_cents(
            plaid_account["balances"].get("available")
            if plaid_account["balances"].get("available") is not None
            else plaid_account["balances"].get("current")
            if plaid_account["balances"].get("current") is not None
            else 0
        ),
        user_id=current_user.id,
    )
    db.add(new_account)
    db.flush()  # assign PK
    db.commit()

    # Kick off the initial sync in the background so this endpoint returns
    # quickly.  We need a fresh session for the background task.
    user_id = current_user.id
    token_id = new_token.id

    def _bg_initial_sync():
        bg_db = SessionLocal()
        try:
            bg_token = bg_db.execute(
                select(TokenORM).where(TokenORM.id == token_id)
            ).scalar_one()
            PlaidService(bg_db).sync_token(bg_token)
            bg_db.commit()
        except Exception:
            bg_db.rollback()
            logger.exception("Background initial sync failed for token %s", token_id)
        finally:
            bg_db.close()

    background_tasks.add_task(_bg_initial_sync)

    return {"message": "Public token exchanged; initial sync started in background."}


# ── Balance ──────────────────────────────────────────────────────────────────


@router.get("/balance/")
async def get_balance(
    account_id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    plaid_svc = PlaidService(db)
    account = plaid_svc.get_balance(account_id, current_user)
    if account is None:
        raise HTTPException(
            status_code=404,
            detail="No balance data returned for this account.",
        )
    return {"account": account}


# ── Sync ─────────────────────────────────────────────────────────────────────


@router.post("/sync-transactions/")
async def sync_transactions(
    background_tasks: BackgroundTasks,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Kick off a Plaid sync (driven by a cursor) for every linked account.

    The sync itself runs as a **background task** so the HTTP response comes
    back right away.
    """
    user_id = current_user.id

    def _bg_sync_all():
        bg_db = SessionLocal()
        try:
            # Look the user up again inside the background session.
            from server.src.db.models import User as UserORM

            user_orm = bg_db.execute(
                select(UserORM).where(UserORM.id == user_id)
            ).scalar_one()

            # Build an object the service can use like a UserInDB.
            bg_user = UserInDB(
                id=user_orm.id,
                username=user_orm.username,
                email=user_orm.email,
                full_name=user_orm.full_name,
                disabled=bool(user_orm.disabled),
                hashed_password=user_orm.hashed_password,
            )

            summaries = PlaidService(bg_db).sync_all_tokens(bg_user)
            logger.info("Sync complete for user %s: %s", user_id, summaries)
            bg_db.commit()
        except Exception:
            bg_db.rollback()
            logger.exception("Background sync failed for user %s", user_id)
        finally:
            bg_db.close()

    background_tasks.add_task(_bg_sync_all)
    return {"status": "sync_started"}
