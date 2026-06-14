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
import random
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.dates import parse_iso_date
from server.src.db.models import Goal as GoalORM, Scenario as ScenarioORM
from server.src.models import (
    DiscreteFlowIn,
    GoalMutationIn,
    RecurringAddIn,
    RecurringOverrideIn,
    ScenarioOverlayIn,
)
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.services.goal_math import add_months, months_to_reach
from server.src.services.read_queries import query_user
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


# --------------------------------------------------------------------------- #
# Evaluate/compare diff helpers (doc 04). Money metrics diff in cents; the
# probability and *_days metrics diff as raw floats/ints.
# --------------------------------------------------------------------------- #

# Money metrics carry dollar values; their delta is computed in cents then
# rendered back to dollars so the diff never accumulates float error.
_MONEY_METRICS = ("lowest_balance", "ending_balance", "safe_to_spend")
# Raw metrics diff directly (a probability in [0,1]; whole days).
_RAW_METRICS = ("overdraft_probability", "runway_days")


def _seed_of(rng: Optional[random.Random]) -> int:
    """A stable integer seed for per-column ``Random``s.

    With a caller-supplied ``Random`` we derive one deterministic draw from it so
    repeated ``evaluate(rng=Random(0))`` calls reproduce; with no rng we still
    return a fixed seed so a column's two engines (forecast + s2s) agree, while
    leaving run-to-run variation to production's unseeded default elsewhere.
    """
    if rng is None:
        return 0
    return rng.randrange(2**31)


def _diff(baseline: dict, scenario: dict) -> dict:
    """Scenario − baseline. Money in cents internally, dollars at the boundary."""
    delta: dict[str, Any] = {}
    for key in _MONEY_METRICS:
        b = dollars_to_cents(baseline[key])
        s = dollars_to_cents(scenario[key])
        delta[key] = cents_to_dollars(s - b)
    for key in _RAW_METRICS:
        delta[key] = scenario[key] - baseline[key]
    # goal_reach: per-goal delta in days (scenario reaches sooner → negative).
    gr: dict[int, dict] = {}
    base_gr = baseline["goal_reach"]
    for goal_id, sc in scenario["goal_reach"].items():
        bd = base_gr.get(goal_id, {}).get("reaches_on")
        sd = sc.get("reaches_on")
        if bd and sd:
            delta_days = (date.fromisoformat(sd) - date.fromisoformat(bd)).days
        else:
            delta_days = None
        gr[goal_id] = {"reaches_on": sd, "delta_days": delta_days}
    delta["goal_reach"] = gr
    return delta


def _runway_days(forecast: dict, as_of: date, horizon_days: int) -> int:
    """Days of runway: to the trough if the balance dips below zero, else the
    full horizon.

    Derived deterministically from the forecast result (no second walk): when
    ``will_go_negative`` the runway ends at ``lowest_date`` (the trough day);
    otherwise the balance never goes negative over the horizon, so runway is the
    whole horizon.
    """
    if not forecast.get("will_go_negative"):
        return horizon_days
    lowest_date = date.fromisoformat(forecast["lowest_date"])
    return max((lowest_date - as_of).days, 0)


def _months_between(start: date, end: date) -> int:
    """Whole calendar months from *start* up to *end* (floor, never negative)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


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

    # -- evaluate + compare (doc 04) ---------------------------------------
    def evaluate(
        self,
        user_id: int,
        overlay: ScenarioOverlay,
        *,
        as_of: Optional[date] = None,
        horizon_days: int = 90,
        rng: Optional[random.Random] = None,
        name: str = "Scenario",
        scenario_id: Optional[int] = None,
    ) -> dict:
        """Baseline-vs-scenario diff over ``[as_of, as_of+horizon_days]``.

        The baseline column always uses :data:`EMPTY`, so it equals live data
        (R1). The scenario column applies ``overlay``; its ``delta`` is
        scenario − baseline, computed in cents and emitted in dollars at the
        boundary (``overdraft_probability`` and ``*_days`` are raw, not money).

        ``rng`` seeds the probabilistic forecast; every column is run from a
        FRESH ``Random`` seeded the same way so identical inputs yield identical
        draws (R5 — apples-to-apples, and an EMPTY scenario diffs to exactly 0).
        """
        as_of = as_of or date.today()
        seed = _seed_of(rng)
        baseline = self._column_result(user_id, EMPTY, as_of, horizon_days, seed)
        scenario = self._column_result(user_id, overlay, as_of, horizon_days, seed)
        return {
            "baseline": {"name": "Baseline", "result": baseline},
            "scenario": {
                "name": name,
                "scenario_id": scenario_id,
                "result": scenario,
                "delta": _diff(baseline, scenario),
            },
        }

    def compare(
        self,
        user_id: int,
        scenario_ids: list[int],
        *,
        as_of: Optional[date] = None,
        horizon_days: int = 90,
        rng: Optional[random.Random] = None,
    ) -> dict:
        """Line up N owned scenarios against one shared baseline column.

        Returns ``{"columns": [baseline, *scenarios]}``; every column runs from a
        Random seeded identically, so the diffs are noise-free across the set
        (R5). A ``scenario_id`` the user does not own raises ``KeyError`` rather
        than silently leaking another user's data.
        """
        as_of = as_of or date.today()
        seed = _seed_of(rng)
        baseline = self._column_result(user_id, EMPTY, as_of, horizon_days, seed)
        columns: list[dict] = [{"name": "Baseline", "result": baseline}]
        for sid in scenario_ids:
            row = self._own(sid, user_id)
            if row is None:
                raise KeyError(f"scenario {sid} not found")
            overlay = _parse_overlay_json(row.overlay_json)
            result = self._column_result(user_id, overlay, as_of, horizon_days, seed)
            columns.append(
                {
                    "name": row.name,
                    "scenario_id": sid,
                    "result": result,
                    "delta": _diff(baseline, result),
                }
            )
        return {"columns": columns}

    # -- internal: one column's metric set ---------------------------------
    def _column_result(
        self,
        user_id: int,
        overlay: ScenarioOverlay,
        as_of: date,
        horizon_days: int,
        seed: int,
    ) -> dict:
        """Compute the metric set for one overlay over the horizon.

        Engines speak dollars; we keep their dollar outputs here and let
        :func:`_diff` re-derive cents for the delta. Each call builds a fresh
        ``Random(seed)`` so two columns with identical inputs draw identically.
        """
        # Lazy import: forecast/spend import recurring which imports this module
        # transitively in some call graphs; importing at call time avoids a
        # circular import at module load.
        from server.src.services.forecast_service import ForecastService
        from server.src.services.spend_service import SpendService

        horizon_end = as_of + timedelta(days=horizon_days)
        fc = ForecastService(self.db).forecast(
            user_id,
            as_of,
            horizon_end,
            include_burn=True,
            rng=random.Random(seed),
            overlay=overlay,
        )

        user = query_user(self.db, user_id)
        s2s = SpendService(self.db).safe_to_spend(
            user,
            as_of,
            include_outlook=False,
            rng=random.Random(seed),
            overlay=overlay,
        )

        return {
            "overdraft_probability": fc["overdraft_probability"],
            "lowest_balance": fc["lowest_balance"],
            "ending_balance": fc["ending_balance"],
            "safe_to_spend": s2s["available"],
            "runway_days": _runway_days(fc, as_of, horizon_days),
            "goal_reach": self._goal_reach(user_id, overlay, as_of),
        }

    def _goal_reach(
        self, user_id: int, overlay: ScenarioOverlay, as_of: date
    ) -> dict[int, dict]:
        """Per-goal reach date under the overlay's goal mutations.

        Pace is the goal's required monthly contribution to hit its deadline at
        baseline; ``goal_mutations`` reshape amount / progress / target_date, so
        injecting progress or cutting the target makes the goal reach sooner.
        Reuses the promoted :func:`months_to_reach` / :func:`add_months`.
        """
        muts = {m.goal_id: m for m in overlay.goal_mutations}
        rows = self.db.execute(
            select(
                GoalORM.id, GoalORM.amount, GoalORM.progress, GoalORM.date
            ).where(GoalORM.user_id == user_id, GoalORM.completed == 0)
        ).all()

        out: dict[int, dict] = {}
        for goal_id, amount_cents, progress_cents, date_str in rows:
            progress_cents = progress_cents or 0
            target = parse_iso_date(date_str) if date_str else None
            mut = muts.get(goal_id)
            if mut is not None:
                if mut.amount_cents is not None:
                    amount_cents = mut.amount_cents
                if mut.progress_cents is not None:
                    progress_cents = mut.progress_cents
                if mut.target_date is not None:
                    target = parse_iso_date(mut.target_date)

            remaining = max(amount_cents - progress_cents, 0)
            # Monthly pace implied by the (possibly mutated) deadline.
            months_left = _months_between(as_of, target) if target else None
            if not months_left or months_left <= 0:
                # No deadline (or already due): reaches as soon as funded, i.e.
                # now if remaining is zero, else unknown.
                reaches_on = as_of.isoformat() if remaining == 0 else None
            else:
                monthly = -(-remaining // months_left) if remaining else 0
                m = months_to_reach(remaining, monthly) if monthly else None
                reaches_on = add_months(as_of, m).isoformat() if m is not None else (
                    as_of.isoformat() if remaining == 0 else None
                )
            out[goal_id] = {"reaches_on": reaches_on}
        return out
