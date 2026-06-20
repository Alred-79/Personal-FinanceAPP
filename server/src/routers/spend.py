"""Spend router. Hands an ORM session to SpendService."""

import statistics

from fastapi import APIRouter, Depends, HTTPException
from datetime import date
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from server.src.services.spend_service import SpendService
from server.src.services import income_smoothing
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.settings import settings
from server.src.db.session import get_db
from server.src.db.models import User as UserORM, Goal as GoalORM
from server.src.money import cents_to_dollars

router = APIRouter(prefix="/spend", tags=["spend"])


def _spend_service(db: Session = Depends(get_db)) -> SpendService:
    return SpendService(db)


def _require_freelancer() -> None:
    """Gate the income-volatility surface behind W5's ship-dark flag (404 when
    off — the wedge is invisible on a standard instance)."""
    if not settings.freelancer_mode_enabled:
        raise HTTPException(
            status_code=404, detail="Freelancer mode is not enabled."
        )


@router.get("/safe-to-spend/")
async def get_safe_to_spend(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    spend_service: SpendService = Depends(_spend_service),
):
    """The dynamic, horizon-anchored Safe-to-Spend number with its breakdown."""
    return spend_service.safe_to_spend(current_user)


@router.get("/budget-allotment/")
async def get_budget_allotment(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    spend_service: SpendService = Depends(_spend_service),
):
    return spend_service.get_budget_allotment(current_user)


@router.get("/spend-over-time/")
async def get_spend_over_time(
    start_date: date,
    end_date: date,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    spend_service: SpendService = Depends(_spend_service),
):
    return spend_service.get_spend_over_time(current_user, start_date, end_date)


# ── W5 freelancer wedge: income volatility + smoothing buffer ────────────────
# Read-only surface over the existing (tested) smoothing recommender. Money is
# dollars at the boundary; the recommender stays cents-native. Applying the
# buffer is the SEPARATE one-tap PUT /settings/preferences/ step (guardrail B2);
# this endpoint only RECOMMENDS and never writes.


class MonthlyIncomePoint(BaseModel):
    month: str  # "YYYY-MM"
    self_employment: float  # dollars
    w2: float  # dollars
    total: float  # dollars


class TaxReserveSummary(BaseModel):
    goal_id: int
    name: str
    target: float  # dollars
    progress: float  # dollars


class IncomeVolatilityResponse(BaseModel):
    months: list[MonthlyIncomePoint]
    months_observed: int
    mean_monthly: float  # dollars (SE mean — the recommender's basis)
    recommended_buffer: float  # dollars
    current_buffer: float  # dollars
    target_percentile: float
    sufficient_data: bool
    rationale: str
    coefficient_of_variation: Optional[float]  # stdev/mean of SE months
    tax_reserve: Optional[TaxReserveSummary]


def _rationale_in_dollars(rec: income_smoothing.SmoothingRecommendation) -> str:
    if not rec.sufficient_data:
        return (
            f"Only {rec.months_observed} month(s) of self-employment income — a "
            "few more are needed to measure how lumpy it is."
        )
    one_in = round(1 / rec.target_percentile) if rec.target_percentile else 5
    return (
        f"Over {rec.months_observed} months your self-employment income averaged "
        f"${cents_to_dollars(rec.mean_monthly_cents):,.0f}/mo. Holding back "
        f"${cents_to_dollars(rec.recommended_buffer_cents):,.0f} smooths a "
        f"1-in-{one_in} low month."
    )


def _tax_reserve_summary(
    db: Session, user_id: int
) -> Optional[TaxReserveSummary]:
    from server.src.services import freelancer_setup

    goal = db.execute(
        select(GoalORM).where(
            GoalORM.user_id == user_id,
            GoalORM.name == freelancer_setup.TAX_RESERVE_GOAL_NAME,
        )
    ).scalar_one_or_none()
    if goal is None:
        return None
    return TaxReserveSummary(
        goal_id=goal.id,
        name=goal.name,
        target=cents_to_dollars(goal.amount),
        progress=cents_to_dollars(goal.progress or 0),
    )


@router.get(
    "/income-volatility/",
    response_model=IncomeVolatilityResponse,
    dependencies=[Depends(_require_freelancer)],
)
async def get_income_volatility(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
    window_months: int = 12,
):
    window = max(1, min(36, window_months))
    rec = income_smoothing.recommend_for_user(
        db, current_user.id, window_months=window
    )
    by_type = income_smoothing.monthly_income_cents_by_type(
        db, current_user.id, window_months=window
    )
    months = [
        MonthlyIncomePoint(
            month=m,
            self_employment=cents_to_dollars(v["self_employment"]),
            w2=cents_to_dollars(v["w2"]),
            total=cents_to_dollars(v["total"]),
        )
        for m, v in by_type.items()
    ]

    se_vals = [v["self_employment"] for v in by_type.values()]
    cov: Optional[float] = None
    if len(se_vals) >= 2:
        mean = statistics.mean(se_vals)
        if mean > 0:
            cov = statistics.pstdev(se_vals) / mean

    user_row = db.get(UserORM, current_user.id)
    current_buffer = (
        cents_to_dollars(user_row.s2s_buffer or 0) if user_row else 0.0
    )

    return IncomeVolatilityResponse(
        months=months,
        months_observed=rec.months_observed,
        mean_monthly=cents_to_dollars(rec.mean_monthly_cents),
        recommended_buffer=cents_to_dollars(rec.recommended_buffer_cents),
        current_buffer=current_buffer,
        target_percentile=rec.target_percentile,
        sufficient_data=rec.sufficient_data,
        rationale=_rationale_in_dollars(rec),
        coefficient_of_variation=cov,
        tax_reserve=_tax_reserve_summary(db, current_user.id),
    )
