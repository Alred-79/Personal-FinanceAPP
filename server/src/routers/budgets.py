"""Budgets router. One envelope budget per category.

Create, read, update, and delete ``Budget`` rows, plus a spent versus limit
summary from ``BudgetService``. Money crosses the boundary as dollar floats
while the DB stores integer cents. A unique constraint keeps it to one budget
per (user, category), so a duplicate category comes back as a 409.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.src.db.models import Budget as BudgetORM
from server.src.db.session import get_db
from server.src.models import Budget as BudgetSchema, UserInDB
from server.src.money import dollars_to_cents
from server.src.services.auth_service import AuthService
from server.src.services.budget_service import BudgetService
from server.src.services.categorization_service import canonicalize_category

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _own_budget(db: Session, budget_id: int, user_id: int) -> BudgetORM:
    budget = db.execute(
        select(BudgetORM).where(
            BudgetORM.id == budget_id, BudgetORM.user_id == user_id
        )
    ).scalar_one_or_none()
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


@router.get("/")
def get_budgets(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Return all budgets with spent / limit / remaining for the current month."""
    return BudgetService(db).summarize(current_user.id)


@router.post("/")
def create_budget(
    budget: BudgetSchema,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    category = canonicalize_category(budget.category)
    new_budget = BudgetORM(
        user_id=current_user.id,
        category=category,
        monthly_limit=dollars_to_cents(budget.monthly_limit),
        rollover=int(budget.rollover),
    )
    db.add(new_budget)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A budget for category '{category}' already exists",
        )
    return {"message": "Budget created successfully"}


@router.put("/{budget_id}/")
def update_budget(
    budget_id: int,
    budget: BudgetSchema,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    existing = _own_budget(db, budget_id, current_user.id)
    category = canonicalize_category(budget.category)
    existing.category = category
    existing.monthly_limit = dollars_to_cents(budget.monthly_limit)
    existing.rollover = int(budget.rollover)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A budget for category '{category}' already exists",
        )
    return {"message": "Budget updated successfully"}


@router.delete("/{budget_id}/")
def delete_budget(
    budget_id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    existing = _own_budget(db, budget_id, current_user.id)
    db.delete(existing)
    db.flush()
    return {"message": "Budget deleted successfully"}
