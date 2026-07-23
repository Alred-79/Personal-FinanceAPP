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
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.dates import parse_iso_date
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    PlanOfRecord as PlanOfRecordORM,
    Scenario as ScenarioORM,
)
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
from server.src.services.recurring_service import project_occurrences
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

# Drift thresholds (doc 06). A committed plan only nags when reality has slipped
# *meaningfully* past the locked snapshot — small noise must stay silent.
#   * overdraft probability that has RISEN by more than this (absolute, [0,1]);
#   * any goal whose reach date has SLIPPED later than the plan by > N days.
_OVERDRAFT_DRIFT_THRESHOLD = 0.10
_GOAL_SLIP_DAYS_THRESHOLD = 14
# The drift job runs from a fixed seed so a re-check on unchanged reality is
# noise-free (the same apples-to-apples discipline ``evaluate`` uses).
_DRIFT_SEED = 0


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
    """Days to the first modeled negative balance, else the full horizon."""
    first_negative = forecast.get("first_negative_date")
    if not first_negative:
        return horizon_days
    return max((date.fromisoformat(first_negative) - as_of).days, 0)


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
        include_series: bool = False,
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
        baseline, baseline_forecast = self._column_evaluation(
            user_id, EMPTY, as_of, horizon_days, seed
        )
        scenario, scenario_forecast = self._column_evaluation(
            user_id, overlay, as_of, horizon_days, seed
        )
        response = {
            "baseline": {"name": "Baseline", "result": baseline},
            "scenario": {
                "name": name,
                "scenario_id": scenario_id,
                "result": scenario,
                "delta": _diff(baseline, scenario),
            },
        }
        if include_series:
            horizon_end = as_of + timedelta(days=horizon_days)
            applied, ignored = self._classify_changes(
                user_id, overlay, as_of, horizon_end
            )
            response.update(
                {
                    "horizon_start": as_of.isoformat(),
                    "horizon_end": horizon_end.isoformat(),
                    "baseline_timeline": baseline_forecast["timeline"],
                    "scenario_timeline": scenario_forecast["timeline"],
                    "baseline_events": baseline_forecast["events"],
                    "scenario_events": scenario_forecast["events"],
                    "applied_changes": applied,
                    "ignored_changes": ignored,
                }
            )
        return response

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

    # -- plan-of-record drift tracking (doc 06) ----------------------------
    def check_drift(
        self,
        user_id: int,
        *,
        as_of: Optional[date] = None,
    ) -> list[int]:
        """Re-check every ACTIVE plan against its locked snapshot.

        For each ``status="active"`` :class:`PlanOfRecord` owned by *user_id*,
        re-evaluate current reality (the EMPTY overlay column = live data) and
        compare it against the metrics locked in ``baseline_snapshot_json`` at
        commit time. When a tracked metric has slipped past threshold — overdraft
        probability risen by more than :data:`_OVERDRAFT_DRIFT_THRESHOLD`, or any
        goal's reach date slipped later by more than
        :data:`_GOAL_SLIP_DAYS_THRESHOLD` days — insert ONE deduped
        ``plan_drift`` notification (``ref=f"plan_drift:{plan_id}:{period}"`` so a
        re-run in the same month is idempotent, a new month can re-fire).

        ``last_checked_at`` is stamped on every plan examined, drift or not.
        Returns the ids of the plans that produced a notification.

        The job is kept light (R7): ``include_outlook=False`` is already implied
        by ``evaluate``'s column path, the scope is active-only, and a fixed
        :data:`_DRIFT_SEED` makes a re-check on unchanged reality noise-free.
        """
        from server.src.services.notification_service import NotificationService

        as_of = as_of or date.today()
        period = as_of.strftime("%Y-%m")
        notifier = NotificationService(self.db)
        drifted: list[int] = []

        plans = (
            self.db.execute(
                select(PlanOfRecordORM).where(
                    PlanOfRecordORM.user_id == user_id,
                    PlanOfRecordORM.status == "active",
                )
            )
            .scalars()
            .all()
        )

        for plan in plans:
            planned = self._snapshot_metrics(plan.baseline_snapshot_json)
            # Current reality is the live (EMPTY-overlay) column, seeded the same
            # way the snapshot's columns were so the comparison is apples-to-apples.
            current = self.evaluate(
                user_id, EMPTY, as_of=as_of, rng=random.Random(_DRIFT_SEED)
            )["baseline"]["result"]

            reasons = self._drift_reasons(planned, current)
            if reasons:
                created = notifier._add_if_new(
                    user_id,
                    type="plan_drift",
                    title="Your committed plan is drifting",
                    message=(
                        f"Plan #{plan.id} has slipped from its committed outlook: "
                        + "; ".join(reasons)
                        + "."
                    ),
                    ref=f"plan_drift:{plan.id}:{period}",
                )
                if created is not None:
                    drifted.append(plan.id)

            plan.last_checked_at = datetime.now()

        self.db.flush()
        return drifted

    @staticmethod
    def _snapshot_metrics(snapshot_json: str) -> dict:
        """The plan's committed-intent metric set from a stored evaluate() dict.

        The snapshot is the full ``evaluate`` payload; the plan's intended state
        is the *scenario* column's ``result`` (the projection under the committed
        overlay), which is what reality is held to.
        """
        snap = json.loads(snapshot_json or "{}")
        return snap.get("scenario", {}).get("result", {}) or {}

    @staticmethod
    def _drift_reasons(planned: dict, current: dict) -> list[str]:
        """Human reasons reality has drifted past threshold, or ``[]`` if within.

        Only DEGRADATION counts: a higher overdraft probability or a *later* goal
        reach date. Reality coming out ahead of plan is never a nag.
        """
        reasons: list[str] = []

        planned_od = planned.get("overdraft_probability")
        current_od = current.get("overdraft_probability")
        if planned_od is not None and current_od is not None:
            if current_od - planned_od > _OVERDRAFT_DRIFT_THRESHOLD:
                reasons.append(
                    f"overdraft risk up {(current_od - planned_od) * 100:.0f}%"
                )

        planned_gr = planned.get("goal_reach", {}) or {}
        current_gr = current.get("goal_reach", {}) or {}
        # The snapshot round-trips goal ids through JSON, so planned keys are
        # strings while a freshly-evaluated current column keys by int. Index
        # current by str() so either side's typing lines up.
        current_by_str = {str(k): v for k, v in current_gr.items()}
        for goal_id, p in planned_gr.items():
            c = current_by_str.get(str(goal_id))
            pd = (p or {}).get("reaches_on")
            cd = (c or {}).get("reaches_on")
            if pd and cd:
                slip = (date.fromisoformat(cd) - date.fromisoformat(pd)).days
                if slip > _GOAL_SLIP_DAYS_THRESHOLD:
                    reasons.append(f"goal {goal_id} reaches {slip} days later")

        return reasons

    # -- internal: one column's metric set ---------------------------------
    def _column_result(
        self,
        user_id: int,
        overlay: ScenarioOverlay,
        as_of: date,
        horizon_days: int,
        seed: int,
    ) -> dict:
        result, _ = self._column_evaluation(
            user_id, overlay, as_of, horizon_days, seed
        )
        return result

    def _column_evaluation(
        self,
        user_id: int,
        overlay: ScenarioOverlay,
        as_of: date,
        horizon_days: int,
        seed: int,
    ) -> tuple[dict, dict]:
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
            horizon_end_override=as_of + timedelta(days=horizon_days),
        )

        result = {
            "overdraft_probability": fc["overdraft_probability"],
            "paths_below_zero": fc["paths_below_zero"],
            "paths_total": fc["paths_total"],
            "lowest_balance": fc["lowest_balance"],
            "ending_balance": fc["ending_balance"],
            "safe_to_spend": s2s["available"],
            "safe_to_spend_horizon_end": s2s["horizon_end"],
            "safe_to_spend_horizon_source": s2s["horizon_source"],
            "runway_days": _runway_days(fc, as_of, horizon_days),
            "first_negative_date": fc.get("first_negative_date"),
            "goal_reach": self._goal_reach(user_id, overlay, as_of),
            # F1: the calibrated trough band + its nominal coverage target ride
            # along so a scenario column can render the same engraved confidence
            # corridor the baseline does. Additive — ``_diff`` ignores them.
            "trough_band": fc.get("trough_band"),
            "coverage_level": fc.get("coverage_level"),
        }
        return result, fc

    def _classify_changes(
        self,
        user_id: int,
        overlay: ScenarioOverlay,
        horizon_start: date,
        horizon_end: date,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Partition every submitted overlay item into applied or ignored.

        This is response metadata only; the stored overlay schema stays stable.
        Reason codes are intentionally small and machine-readable so the client
        can offer an Extend horizon action without parsing prose.
        """
        applied: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []

        def accept(identifier: str, kind: str, detail: str) -> None:
            applied.append({"id": identifier, "kind": kind, "detail": detail})

        def reject(
            identifier: str, kind: str, reason_code: str, detail: str
        ) -> None:
            ignored.append(
                {
                    "id": identifier,
                    "kind": kind,
                    "reason_code": reason_code,
                    "detail": detail,
                }
            )

        for i, add in enumerate(overlay.added_recurring):
            identifier = f"added_recurring:{i}"
            anchor = parse_iso_date(add.anchor_date) if add.anchor_date else horizon_start
            occurrences = (
                project_occurrences(
                    anchor, add.recurrence, horizon_start, horizon_end
                )
                if anchor is not None
                else []
            )
            if occurrences:
                accept(identifier, add.kind, f"{add.title} occurs inside this horizon")
            else:
                reject(
                    identifier,
                    add.kind,
                    "no_occurrence_in_horizon",
                    f"{add.title} has no occurrence inside this horizon",
                )

        for i, flow in enumerate(overlay.discrete_flows):
            identifier = f"discrete_flow:{i}"
            flow_date = parse_iso_date(flow.date)
            if flow_date is not None and horizon_start <= flow_date <= horizon_end:
                accept(identifier, flow.kind, f"{flow.title or 'One-time flow'} on {flow.date}")
            else:
                reject(
                    identifier,
                    flow.kind,
                    "outside_horizon",
                    f"{flow.title or 'One-time flow'} falls outside this horizon",
                )

        for i, (kind, source_id) in enumerate(sorted(overlay.excluded_source_ids)):
            identifier = f"excluded_source:{i}"
            if self._source_exists(user_id, kind, source_id):
                accept(identifier, kind, f"Excluded {kind} source {source_id}")
            else:
                reject(identifier, kind, "source_not_found", f"Source {source_id} was not found")

        for i, override in enumerate(overlay.overridden_recurring):
            identifier = f"overridden_recurring:{i}"
            if self._source_exists(user_id, override.kind, override.source_id):
                accept(identifier, override.kind, f"Changed source {override.source_id}")
            else:
                reject(
                    identifier,
                    override.kind,
                    "source_not_found",
                    f"Source {override.source_id} was not found",
                )

        owned_goal_ids = set(
            self.db.execute(
                select(GoalORM.id).where(GoalORM.user_id == user_id)
            ).scalars()
        )
        for i, mutation in enumerate(overlay.goal_mutations):
            identifier = f"goal_mutation:{i}"
            if mutation.goal_id in owned_goal_ids:
                accept(identifier, "goal", f"Changed goal {mutation.goal_id}")
            else:
                reject(
                    identifier,
                    "goal",
                    "goal_not_found",
                    f"Goal {mutation.goal_id} was not found",
                )

        if overlay.balance_override_cents is not None:
            accept("balance_override", "balance", "Changed the starting balance")

        for key in sorted(overlay.config_overrides):
            reject(
                f"config_override:{key}",
                "config",
                "unsupported_config",
                f"Setting {key} is not supported by decision evaluation",
            )
        return applied, ignored

    def _source_exists(self, user_id: int, kind: str, source_id: int) -> bool:
        model = IncomeORM if kind == "income" else ExpenseORM if kind == "expense" else None
        if model is None:
            return False
        return (
            self.db.execute(
                select(model.id)
                .join(AccountORM, model.account_id == AccountORM.id)
                .where(model.id == source_id, AccountORM.user_id == user_id)
            ).scalar_one_or_none()
            is not None
        )

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
