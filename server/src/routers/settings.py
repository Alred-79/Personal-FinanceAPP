"""Settings router. Consolidates user preferences and exposes read-only AI config.

The spend-warning and savings-percent preferences used to live on the users
router. They now sit here, alongside a read-only view of the assistant's model
configuration. Updates assign ORM attributes (parameterized), so there's no SQL
injection surface, mirroring the pattern in ``routers/users.py``.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.settings import settings as app_settings
from server.src.db.session import get_db
from server.src.db.models import User as UserORM

router = APIRouter(prefix="/settings", tags=["settings"])


class Preferences(BaseModel):
    spend_warning: int
    savings_percent: int


class AIConfig(BaseModel):
    model: str
    available_models: list[str]


class SettingsResponse(BaseModel):
    preferences: Preferences
    ai: AIConfig


class PreferencesUpdate(BaseModel):
    """Partial update: only the fields that are sent get changed."""

    spend_warning: Optional[int] = Field(default=None, ge=0, le=100)
    savings_percent: Optional[int] = Field(default=None, ge=0, le=100)


@router.get("/", response_model=SettingsResponse)
async def get_settings(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
):
    return SettingsResponse(
        preferences=Preferences(
            spend_warning=current_user.spend_warning,
            savings_percent=current_user.savings_percent,
        ),
        ai=AIConfig(
            model=app_settings.groq_chat_model,
            available_models=app_settings.assistant_available_models,
        ),
    )


@router.put("/preferences/", response_model=Preferences)
async def update_preferences(
    payload: PreferencesUpdate,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    if payload.spend_warning is None and payload.savings_percent is None:
        raise HTTPException(status_code=400, detail="No preferences to update.")

    user_row = db.execute(
        select(UserORM).where(UserORM.id == current_user.id)
    ).scalar_one()
    if payload.spend_warning is not None:
        user_row.spend_warning = payload.spend_warning
    if payload.savings_percent is not None:
        user_row.savings_percent = payload.savings_percent
    db.flush()

    return Preferences(
        spend_warning=user_row.spend_warning,
        savings_percent=user_row.savings_percent,
    )
