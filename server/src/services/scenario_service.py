"""Scenario CRUD service (v6 doc 03).

Owns the boundary between the dollar-denominated API contract
(:class:`server.src.models.ScenarioOverlayIn`) and the cents-only, DB-free
:class:`server.src.services.scenario_overlay.ScenarioOverlay`.

The seam runs in exactly two places, and only here:

* ``overlay_to_json`` (in) — a dollar ``ScenarioOverlayIn`` is converted to a
  cents ``ScenarioOverlay`` and serialized to the schema-versioned dict that
  lands in ``scenarios.overlay_json``. No float reaches storage.
* ``overlay_from_json`` (out) — the stored dict is parsed back to a cents
  ``ScenarioOverlay`` and rendered to a dollar ``ScenarioOverlayIn`` for the
  response.

Every method is ownership-scoped on ``user_id``; a row owned by another user is
indistinguishable from a missing one (the router turns ``None`` into a 404).
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import Scenario as ScenarioORM
from server.src.models import (
    DiscreteFlowIn,
    GoalMutationIn,
    RecurringAddIn,
    RecurringOverrideIn,
    ScenarioOverlayIn,
)
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.services.scenario_overlay import (
    EMPTY,
    DiscreteFlow,
    GoalMutation,
    RecurringAdd,
    RecurringOverride,
    ScenarioOverlay,
    overlay_from_json,
    overlay_to_json,
)


def _parse_overlay_json(raw: Optional[str]) -> ScenarioOverlay:
    """Parse stored ``overlay_json`` to a domain overlay.

    An empty/absent column (the table's ``server_default`` is ``"{}"`` for rows
    inserted outside this service) deserializes to the identity overlay rather
    than tripping the schema-version guard.
    """
    d = json.loads(raw or "{}")
    if not d:
        return EMPTY
    return overlay_from_json(d)


def _cents(dollars: Optional[float]) -> Optional[int]:
    """Dollar float → integer cents, preserving ``None``."""
    return None if dollars is None else dollars_to_cents(dollars)


def _dollars(cents: Optional[int]) -> Optional[float]:
    """Integer cents → dollar float, preserving ``None``."""
    return None if cents is None else cents_to_dollars(cents)


def overlay_in_to_overlay(overlay_in: ScenarioOverlayIn) -> ScenarioOverlay:
    """Convert a dollar API overlay to the cents-only domain overlay."""
    return ScenarioOverlay(
        added_recurring=tuple(
            RecurringAdd(
                title=a.title,
                amount_cents=dollars_to_cents(a.amount),
                recurrence=a.recurrence,
                kind=a.kind,
                category=a.category,
                anchor_date=a.anchor_date,
            )
            for a in overlay_in.added_recurring
        ),
        excluded_source_ids=frozenset(
            (kind, sid) for (kind, sid) in overlay_in.excluded_source_ids
        ),
        overridden_recurring=tuple(
            RecurringOverride(
                source_id=o.source_id,
                kind=o.kind,
                amount_cents=_cents(o.amount),
                recurrence=o.recurrence,
            )
            for o in overlay_in.overridden_recurring
        ),
        discrete_flows=tuple(
            DiscreteFlow(
                date=f.date,
                amount_cents=dollars_to_cents(f.amount),
                kind=f.kind,
                title=f.title,
                category=f.category,
            )
            for f in overlay_in.discrete_flows
        ),
        goal_mutations=tuple(
            GoalMutation(
                goal_id=g.goal_id,
                amount_cents=_cents(g.amount),
                target_date=g.target_date,
                progress_cents=_cents(g.progress),
                name=g.name,
            )
            for g in overlay_in.goal_mutations
        ),
        balance_override_cents=_cents(overlay_in.balance_override),
        config_overrides=dict(overlay_in.config_overrides),
    )


def overlay_to_overlay_in(overlay: ScenarioOverlay) -> ScenarioOverlayIn:
    """Convert the cents-only domain overlay back to a dollar API overlay."""
    return ScenarioOverlayIn(
        added_recurring=[
            RecurringAddIn(
                title=a.title,
                amount=cents_to_dollars(a.amount_cents),
                recurrence=a.recurrence,
                kind=a.kind,
                category=a.category,
                anchor_date=a.anchor_date,
            )
            for a in overlay.added_recurring
        ],
        excluded_source_ids=[
            (kind, sid) for (kind, sid) in sorted(overlay.excluded_source_ids)
        ],
        overridden_recurring=[
            RecurringOverrideIn(
                source_id=o.source_id,
                kind=o.kind,
                amount=_dollars(o.amount_cents),
                recurrence=o.recurrence,
            )
            for o in overlay.overridden_recurring
        ],
        discrete_flows=[
            DiscreteFlowIn(
                date=f.date,
                amount=cents_to_dollars(f.amount_cents),
                kind=f.kind,
                title=f.title,
                category=f.category,
            )
            for f in overlay.discrete_flows
        ],
        goal_mutations=[
            GoalMutationIn(
                goal_id=g.goal_id,
                amount=_dollars(g.amount_cents),
                target_date=g.target_date,
                progress=_dollars(g.progress_cents),
                name=g.name,
            )
            for g in overlay.goal_mutations
        ],
        balance_override=_dollars(overlay.balance_override_cents),
        config_overrides=dict(overlay.config_overrides),
    )


class ScenarioService:
    """CRUD over saved scenarios, scoped to one user."""

    def __init__(self, db: Session):
        self.db = db

    # -- internal -----------------------------------------------------------
    def _own(self, scenario_id: int, user_id: int) -> Optional[ScenarioORM]:
        return self.db.execute(
            select(ScenarioORM).where(
                ScenarioORM.id == scenario_id, ScenarioORM.user_id == user_id
            )
        ).scalar_one_or_none()

    # -- CRUD ---------------------------------------------------------------
    def create(
        self, user_id: int, name: str, overlay_in: ScenarioOverlayIn
    ) -> ScenarioORM:
        """Create a scenario, converting the dollar overlay to cents JSON."""
        overlay = overlay_in_to_overlay(overlay_in)
        row = ScenarioORM(
            user_id=user_id,
            name=name,
            overlay_json=json.dumps(overlay_to_json(overlay)),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list(self, user_id: int) -> list[ScenarioORM]:
        return list(
            self.db.execute(
                select(ScenarioORM)
                .where(ScenarioORM.user_id == user_id)
                .order_by(ScenarioORM.id.desc())
            )
            .scalars()
            .all()
        )

    def get(self, user_id: int, scenario_id: int) -> Optional[ScenarioORM]:
        return self._own(scenario_id, user_id)

    def update(
        self, user_id: int, scenario_id: int, name: str, overlay_in: ScenarioOverlayIn
    ) -> Optional[ScenarioORM]:
        row = self._own(scenario_id, user_id)
        if row is None:
            return None
        overlay = overlay_in_to_overlay(overlay_in)
        row.name = name
        row.overlay_json = json.dumps(overlay_to_json(overlay))
        self.db.flush()
        return row

    def delete(self, user_id: int, scenario_id: int) -> bool:
        row = self._own(scenario_id, user_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    def load_overlay(self, user_id: int, scenario_id: int) -> Optional[ScenarioOverlay]:
        """Return the cents-only domain overlay for a scenario, or ``None``.

        This is the seam consumers (evaluate/compare, doc 04) thread into the
        projection — they get a ready ``ScenarioOverlay``, not raw JSON.
        """
        row = self._own(scenario_id, user_id)
        if row is None:
            return None
        return _parse_overlay_json(row.overlay_json)

    # -- serialization for responses ---------------------------------------
    @staticmethod
    def to_out_dict(row: ScenarioORM) -> dict:
        """Render an ORM row to the ``ScenarioOut`` shape (dollar overlay)."""
        overlay = _parse_overlay_json(row.overlay_json)
        return {
            "id": row.id,
            "name": row.name,
            "overlay": overlay_to_overlay_in(overlay).model_dump(),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
