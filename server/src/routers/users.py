"""Users router. Uses the ORM, so settings updates are safe from SQL injection.

The ``update-spend-warning`` and ``update-savings-percent`` endpoints used to
build SQL through string formatting, which left them open to injection. Now they
just assign ORM attributes, which get parameterized for us.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.models import User, UserInDB
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db
from server.src.db.models import User as UserORM
from server.src.settings import settings

router = APIRouter(prefix="/users", tags=["users"])

_auth_service = AuthService()


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/me/", response_model=User)
async def read_users_me(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
):
    return current_user


@router.put("/me/change-password/")
async def change_password(
    req: PasswordChangeRequest,
    response: Response,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    # 1) Prove the caller knows the current password (wrong -> 400, no change).
    if not _auth_service.verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    # 2) Enforce password strength BEFORE hashing the new one (weak -> 422 with
    #    the exact rules, so the user can fix it in one try).
    AuthService.validate_password_strength(req.new_password)

    # 3) Update the hash.
    user_row = db.execute(
        select(UserORM).where(UserORM.id == current_user.id)
    ).scalar_one()
    user_row.hashed_password = _auth_service.get_password_hash(req.new_password)
    db.flush()

    # 4) Changing a password almost always means "lock everyone else out". Revoke
    #    EVERY existing refresh-token family for this user (kills stolen/other
    #    sessions), then immediately mint a fresh cookie pair for THIS session so
    #    the user isn't bounced out of the tab they just acted from.
    AuthService.revoke_all_user_tokens(db, current_user.id)

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    new_access = _auth_service.create_access_token(
        data={"sub": current_user.username}, expires_delta=access_token_expires
    )
    new_refresh = _auth_service.create_refresh_token(db, current_user.id)
    _auth_service.set_auth_cookies(response, new_access, new_refresh)

    return {"message": "Password updated successfully"}
