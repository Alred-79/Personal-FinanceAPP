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
# v4 package 02: the game intensity dial — one variable end to end.
_GAME_MODES = ("off", "ambient", "full")


class Preferences(BaseModel):
    spend_warning: int
    savings_percent: int
    # Safe-to-Spend config (v1): the rules behind the one number.
    s2s_horizon: str = "paycheck"
    s2s_include_income: bool = True
    s2s_include_goals: bool = True
    s2s_buffer: float = 0.0  # dollars at the API boundary
    birth_year: Optional[int] = None
    # v4 package 02: 'off' | 'ambient' | 'full'. Off = today's app exactly.
    game_mode: str = "off"
    # Pillar 2B: the bounded auto-execute threshold, in DOLLARS at the boundary
    # (stored as cents). An auto-fund rule firing at or below this earmarks
    # silently; above it the agent surfaces a one-tap proposal instead. $100
    # default. Virtual money only — never gates a real transfer.
    auto_execute_threshold: float = 100.0


class AIConfig(BaseModel):
    model: str
    available_models: list[str]


class FeatureFlags(BaseModel):
    """Server-side feature flags the client needs to gate UI (e.g. the tax nav).

    Distinct from user preferences: these are instance-level toggles the user
    cannot change — the client only reads them to decide what surfaces to show.
    """

    tax_features_enabled: bool
    # W8 — when on, the client defaults the home surface to the single
    # "one thing today" next-action view. The endpoint works regardless (B4); this
    # flag only drives the client's DEFAULTING to it. Instance-level, read-only.
    neurodivergent_mode: bool


class SettingsResponse(BaseModel):
    preferences: Preferences
    ai: AIConfig
    features: FeatureFlags


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
    game_mode: Optional[str] = Field(default=None)
    auto_execute_threshold: Optional[float] = Field(
        default=None, ge=0, le=1_000_000_000, allow_inf_nan=False
    )


def _to_preferences(user_row: UserORM) -> Preferences:
    return Preferences(
        spend_warning=user_row.spend_warning,
        savings_percent=user_row.savings_percent,
        s2s_horizon=user_row.s2s_horizon or "paycheck",
        s2s_include_income=bool(user_row.s2s_include_income),
        s2s_include_goals=bool(user_row.s2s_include_goals),
        s2s_buffer=cents_to_dollars(user_row.s2s_buffer or 0),
        birth_year=user_row.birth_year,
        game_mode=user_row.game_mode or "off",
        auto_execute_threshold=cents_to_dollars(
            user_row.auto_execute_threshold_cents
            if user_row.auto_execute_threshold_cents is not None
            else 10000
        ),
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
        features=FeatureFlags(
            tax_features_enabled=app_settings.tax_features_enabled,
            neurodivergent_mode=app_settings.neurodivergent_mode,
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
    if payload.game_mode is not None and payload.game_mode not in _GAME_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"game_mode must be one of {_GAME_MODES}",
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
    if payload.auto_execute_threshold is not None:
        user_row.auto_execute_threshold_cents = dollars_to_cents(
            payload.auto_execute_threshold
        )
    if "birth_year" in payload.model_fields_set:
        user_row.birth_year = payload.birth_year
    if payload.game_mode is not None:
        # A settings change is NOT a financial action — it emits no game events
        # (XP hygiene, v4 Law 3). We just persist the new mode.
        new_mode = payload.game_mode
        if new_mode != "off":
            # v4 package 10: first game activation assigns the experiment
            # cohort (stable hash). Holdout users keep the full Money Spine —
            # alerts, the number, what-if, graduation — but the game layer
            # stays locked 'off' (withholding the spine would be unethical
            # AND would pollute the question the holdout exists to answer).
            from server.src.services.game.experiments import (
                COHORT_HOLDOUT,
                ensure_cohort,
            )

            if ensure_cohort(db, user_row.id) == COHORT_HOLDOUT:
                new_mode = "off"
        user_row.game_mode = new_mode
    db.flush()

    return _to_preferences(user_row)
