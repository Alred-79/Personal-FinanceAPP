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
from server.src.money import cents_to_dollars, dollars_to_cents

router = APIRouter(prefix="/settings", tags=["settings"])


_S2S_HORIZONS = ("paycheck", "month", "week")


class Preferences(BaseModel):
    spend_warning: int
    savings_percent: int
    # Safe-to-Spend config (v1): the rules behind the one number.
    s2s_horizon: str = "paycheck"
    s2s_include_income: bool = True
    s2s_include_goals: bool = True
    s2s_buffer: float = 0.0  # dollars at the API boundary
    birth_year: Optional[int] = None


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
    s2s_horizon: Optional[str] = Field(default=None)
    s2s_include_income: Optional[bool] = None
    s2s_include_goals: Optional[bool] = None
    s2s_buffer: Optional[float] = Field(
        default=None, ge=0, le=1_000_000_000, allow_inf_nan=False
    )
    birth_year: Optional[int] = Field(default=None, ge=1900, le=2100)


def _to_preferences(user_row: UserORM) -> Preferences:
    return Preferences(
        spend_warning=user_row.spend_warning,
        savings_percent=user_row.savings_percent,
        s2s_horizon=user_row.s2s_horizon or "paycheck",
        s2s_include_income=bool(user_row.s2s_include_income),
        s2s_include_goals=bool(user_row.s2s_include_goals),
        s2s_buffer=cents_to_dollars(user_row.s2s_buffer or 0),
        birth_year=user_row.birth_year,
    )


@router.get("/", response_model=SettingsResponse)
async def get_settings(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    user_row = db.execute(
        select(UserORM).where(UserORM.id == current_user.id)
    ).scalar_one()
    return SettingsResponse(
        preferences=_to_preferences(user_row),
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
    if not payload.model_fields_set:
        raise HTTPException(status_code=400, detail="No preferences to update.")
    if payload.s2s_horizon is not None and payload.s2s_horizon not in _S2S_HORIZONS:
        raise HTTPException(
            status_code=422,
            detail=f"s2s_horizon must be one of {_S2S_HORIZONS}",
        )

    user_row = db.execute(
        select(UserORM).where(UserORM.id == current_user.id)
    ).scalar_one()
    if payload.spend_warning is not None:
        user_row.spend_warning = payload.spend_warning
    if payload.savings_percent is not None:
        user_row.savings_percent = payload.savings_percent
    if payload.s2s_horizon is not None:
        user_row.s2s_horizon = payload.s2s_horizon
    if payload.s2s_include_income is not None:
        user_row.s2s_include_income = int(payload.s2s_include_income)
    if payload.s2s_include_goals is not None:
        user_row.s2s_include_goals = int(payload.s2s_include_goals)
    if payload.s2s_buffer is not None:
        user_row.s2s_buffer = dollars_to_cents(payload.s2s_buffer)
    if "birth_year" in payload.model_fields_set:
        user_row.birth_year = payload.birth_year
    db.flush()

    return _to_preferences(user_row)
