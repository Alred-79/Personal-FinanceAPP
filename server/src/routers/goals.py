"""Goals router. Uses the ORM and stores money as integer cents.

Create, read, update, and delete financial goals. Amounts and progress flip
between dollar floats (API) and integer cents (DB) right at the boundary.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.models import Goal as GoalSchema, User, UserInDB
from server.src.services.auth_service import AuthService
from server.src.db.session import get_db
from server.src.db.models import Goal as GoalORM
from server.src.money import dollars_to_cents, cents_to_dollars

router = APIRouter(prefix="/goals", tags=["goals"])


def _goal_to_dict(goal: GoalORM) -> dict:
    """Serialize an ORM Goal row to a dict with dollar amounts."""
    return {
        "id": goal.id,
        "name": goal.name,
        "description": goal.description,
        "amount": cents_to_dollars(goal.amount),
        "date": goal.date,
        "user_id": goal.user_id,
        "completed": bool(goal.completed),
        "progress": cents_to_dollars(goal.progress),
    }


@router.get("/")
def get_goals(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    goals = (
        db.execute(select(GoalORM).where(GoalORM.user_id == current_user.id))
        .scalars()
        .all()
    )
    # W8 visual jars: include each goal's W7 (F4) soft earmark sub-buckets so the
    # client can render named partitions of Goal.progress without a second round
    # trip. The earmarks are read-only here; they're created/edited via the
    # behavioral surface (EarmarkService). Empty list when none / flag off.
    from server.src.services.behavioral import EarmarkService

    earmark_svc = EarmarkService(db)
    out = []
    for g in goals:
        d = _goal_to_dict(g)
        d["earmarks"] = earmark_svc.list(current_user.id, g.id)
        out.append(d)
    return out


@router.get("/{goal_id}/earmarks/")
def get_goal_earmarks(
    goal_id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """W8 visual jars — the soft earmark sub-buckets (W7 F4) over a goal's
    ``Goal.progress``. Read-only; mutations live on the behavioral surface.

    Ownership is enforced by the goal lookup (a foreign/missing goal → 404), so a
    user can never read another user's earmark partitions.
    """
    goal = db.execute(
        select(GoalORM).where(
            GoalORM.id == goal_id, GoalORM.user_id == current_user.id
        )
    ).scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    from server.src.services.behavioral import EarmarkService

    return {"goal_id": goal_id, "earmarks": EarmarkService(db).list(current_user.id, goal_id)}


@router.post("/")
def create_goal(
    goal: GoalSchema,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    new_goal = GoalORM(
        user_id=current_user.id,
        name=goal.name,
        description=goal.description,
        amount=dollars_to_cents(goal.amount),
        date=str(goal.date),
        completed=int(goal.completed),
        progress=dollars_to_cents(goal.progress),
    )
    db.add(new_goal)
    db.flush()
    return {"message": "Goal created successfully"}


@router.put("/{goal_id}/")
def update_goal(
    goal_id: int,
    goal: GoalSchema,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    existing = db.execute(
        select(GoalORM).where(
            GoalORM.id == goal_id, GoalORM.user_id == current_user.id
        )
    ).scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Goal not found")

    existing.name = goal.name
    existing.description = goal.description
    existing.amount = dollars_to_cents(goal.amount)
    existing.date = str(goal.date)
    existing.completed = int(goal.completed)
    existing.progress = dollars_to_cents(goal.progress)
    db.flush()
    return {"message": "Goal updated successfully"}


@router.delete("/{goal_id}/")
def delete_goal(
    goal_id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    existing = db.execute(
        select(GoalORM).where(
            GoalORM.id == goal_id, GoalORM.user_id == current_user.id
        )
    ).scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Goal not found")

    db.delete(existing)
    db.flush()
    return {"message": "Goal deleted successfully"}
