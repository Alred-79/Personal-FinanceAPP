"""Users router. Uses the ORM, so settings updates are safe from SQL injection.

The ``update-spend-warning`` and ``update-savings-percent`` endpoints used to
build SQL through string formatting, which left them open to injection. Now they
just assign ORM attributes, which get parameterized for us.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.models import User, UserInDB
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db
from server.src.db.models import User as UserORM

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
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    if not _auth_service.verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    user_row = db.execute(
        select(UserORM).where(UserORM.id == current_user.id)
    ).scalar_one()
    user_row.hashed_password = _auth_service.get_password_hash(req.new_password)
    db.flush()
    return {"message": "Password updated successfully"}
