"""Spend router. Hands an ORM session to SpendService."""

from fastapi import APIRouter, Depends
from datetime import date
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.services.spend_service import SpendService
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db

router = APIRouter(prefix="/spend", tags=["spend"])


def _spend_service(db: Session = Depends(get_db)) -> SpendService:
    return SpendService(db)


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
