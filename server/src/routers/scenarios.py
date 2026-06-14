"""Scenarios router (v6 doc 03). CRUD over saved, named hypotheticals.

A scenario is a stored :class:`~server.src.services.scenario_overlay.ScenarioOverlay`.
The router speaks dollar floats on the wire (``ScenarioOverlayIn``); the
``ScenarioService`` owns the dollar↔cents seam so nothing here touches money math.
Every route is ownership-scoped — another user's id is a 404, never a leak.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import ScenarioCompareIn, ScenarioIn, UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.scenario_service import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

_DEFAULT_HORIZON_DAYS = 90
_MAX_HORIZON_DAYS = 3650


@router.get("/")
async def list_scenarios(
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    svc = ScenarioService(db)
    return [svc.to_out_dict(s) for s in svc.list(current_user.id)]


@router.post("/")
async def create_scenario(
    scenario: ScenarioIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    svc = ScenarioService(db)
    row = svc.create(current_user.id, scenario.name, scenario.overlay)
    return svc.to_out_dict(row)


@router.get("/{scenario_id}/")
async def get_scenario(
    scenario_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    svc = ScenarioService(db)
    row = svc.get(current_user.id, scenario_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return svc.to_out_dict(row)


@router.put("/{scenario_id}/")
async def update_scenario(
    scenario_id: int,
    scenario: ScenarioIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    svc = ScenarioService(db)
    row = svc.update(current_user.id, scenario_id, scenario.name, scenario.overlay)
    if row is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return svc.to_out_dict(row)


@router.delete("/{scenario_id}/")
async def delete_scenario(
    scenario_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    svc = ScenarioService(db)
    if not svc.delete(current_user.id, scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"message": "Scenario deleted successfully"}


@router.post("/compare/")
async def compare_scenarios(
    payload: ScenarioCompareIn,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Diff N owned scenarios against one shared baseline column.

    Production leaves ``rng`` unseeded; the values returned are dollars at the
    boundary, deltas computed in cents server-side. A scenario id the caller
    does not own is a 404 (no cross-user leak).
    """
    horizon = min(payload.horizon_days, _MAX_HORIZON_DAYS)
    try:
        return ScenarioService(db).compare(
            current_user.id, payload.scenario_ids, horizon_days=horizon
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Scenario not found")


@router.post("/{scenario_id}/evaluate/")
async def evaluate_scenario(
    scenario_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    horizon_days: int = _DEFAULT_HORIZON_DAYS,
    db: Session = Depends(get_db),
):
    """Baseline-vs-scenario diff for one saved scenario over the horizon."""
    horizon = min(max(horizon_days, 1), _MAX_HORIZON_DAYS)
    svc = ScenarioService(db)
    overlay = svc.load_overlay(current_user.id, scenario_id)
    row = svc.get(current_user.id, scenario_id)
    if overlay is None or row is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return svc.evaluate(
        current_user.id,
        overlay,
        horizon_days=horizon,
        name=row.name,
        scenario_id=row.id,
    )
