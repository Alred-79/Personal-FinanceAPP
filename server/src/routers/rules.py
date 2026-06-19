"""Rules router (v1 Layer B). CRUD + dry-run preview.

The engine itself runs inside ``TransactionService.create``; this router only
manages rule definitions. There is deliberately no standalone rules page in the
UI — rules are embedded where the money lands (the Goal dialog's Auto-fund
section, budget alerts), so this API is shaped for those embedded editors.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import Goal as GoalORM, Rule as RuleORM
from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.rule_engine import ACTION_TYPES, RuleEngine

router = APIRouter(prefix="/rules", tags=["rules"])

_TARGET_KINDS = ("goal",)  # v4 adds 'liability' here with no migration


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    conditions: list[dict[str, Any]] = []
    action_type: str
    action_params: dict[str, Any] = {}
    target_kind: Optional[str] = None
    target_id: Optional[int] = None
    priority: int = 0


class RulePreviewIn(BaseModel):
    conditions: list[dict[str, Any]] = []
    action_type: str
    action_params: dict[str, Any] = {}
    sample_txns: list[dict[str, Any]] = []


def _validate(rule: RuleIn, user_id: int, db: Session) -> None:
    if rule.action_type not in ACTION_TYPES:
        raise HTTPException(
            status_code=422, detail=f"action_type must be one of {ACTION_TYPES}"
        )
    if rule.action_type in ("allocate", "roundup"):
        if rule.target_kind not in _TARGET_KINDS or rule.target_id is None:
            raise HTTPException(
                status_code=422,
                detail="allocate/roundup rules need target_kind='goal' and a target_id",
            )
        goal = db.execute(
            select(GoalORM.id).where(
                GoalORM.id == rule.target_id, GoalORM.user_id == user_id
            )
        ).scalar_one_or_none()
        if goal is None:
            raise HTTPException(status_code=404, detail="Target goal not found")


def _to_dict(rule: RuleORM) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "enabled": bool(rule.enabled),
        "conditions": json.loads(rule.conditions or "[]"),
        "action_type": rule.action_type,
        "action_params": json.loads(rule.action_params or "{}"),
        "target_kind": rule.target_kind,
        "target_id": rule.target_id,
        "priority": rule.priority,
        "created_at": rule.created_at,
    }


def _own_rule(rule_id: int, user_id: int, db: Session) -> RuleORM:
    rule = db.execute(
        select(RuleORM).where(RuleORM.id == rule_id, RuleORM.user_id == user_id)
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.get("/")
async def list_rules(
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    target_kind: Optional[str] = None,
    target_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List rules; filterable by target so embedded editors fetch only theirs."""
    query = select(RuleORM).where(RuleORM.user_id == current_user.id)
    if target_kind is not None:
        query = query.where(RuleORM.target_kind == target_kind)
    if target_id is not None:
        query = query.where(RuleORM.target_id == target_id)
    rules = db.execute(query.order_by(RuleORM.priority.desc())).scalars().all()
    return [_to_dict(r) for r in rules]


@router.post("/")
async def create_rule(
    rule: RuleIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    _validate(rule, current_user.id, db)
    row = RuleORM(
        user_id=current_user.id,
        name=rule.name,
        enabled=int(rule.enabled),
        conditions=json.dumps(rule.conditions),
        action_type=rule.action_type,
        action_params=json.dumps(rule.action_params),
        target_kind=rule.target_kind,
        target_id=rule.target_id,
        priority=rule.priority,
    )
    db.add(row)
    db.flush()
    return _to_dict(row)


@router.put("/{rule_id}/")
async def update_rule(
    rule_id: int,
    rule: RuleIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    _validate(rule, current_user.id, db)
    row = _own_rule(rule_id, current_user.id, db)
    row.name = rule.name
    row.enabled = int(rule.enabled)
    row.conditions = json.dumps(rule.conditions)
    row.action_type = rule.action_type
    row.action_params = json.dumps(rule.action_params)
    row.target_kind = rule.target_kind
    row.target_id = rule.target_id
    row.priority = rule.priority
    db.flush()
    return _to_dict(row)


class RulePauseIn(BaseModel):
    enabled: bool


@router.patch("/{rule_id}/")
async def set_rule_enabled(
    rule_id: int,
    body: RulePauseIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Pause or resume a rule (W9 management surface).

    A dedicated toggle so the management UI can pause ANY rule — including the
    auto-created W4/W5/W7 rules whose full shape the user never typed — without
    re-submitting (and re-validating) the whole definition. Pause takes effect
    immediately: ``RuleEngine`` reads ``enabled == 1`` live from the DB on every
    transaction and is constructed per batch, so flipping this column IS the
    cache invalidation — there is no separate rule-firing cache to clear.
    """
    row = _own_rule(rule_id, current_user.id, db)
    row.enabled = int(body.enabled)
    db.flush()
    return _to_dict(row)


@router.delete("/{rule_id}/")
async def delete_rule(
    rule_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    row = _own_rule(rule_id, current_user.id, db)
    db.delete(row)
    db.flush()
    return {"message": "Rule deleted successfully"}


@router.post("/preview/")
async def preview_rule(
    payload: RulePreviewIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Dry-run a rule shape against sample transactions. Nothing is written."""
    if payload.action_type not in ACTION_TYPES:
        raise HTTPException(
            status_code=422, detail=f"action_type must be one of {ACTION_TYPES}"
        )
    return RuleEngine(db).preview(
        {
            "conditions": payload.conditions,
            "action_type": payload.action_type,
            "action_params": payload.action_params,
        },
        payload.sample_txns,
    )
