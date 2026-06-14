"""What-if with commit (v4 §5.4, R14).

Given a small delta to a goal (e.g. +$X/month), recompute the goal's reach date
and present a result that terminates in exactly ONE commit action. The R14 rules
are hard requirements, not suggestions:

  - The DEFAULT scenario is reachable and slightly better — the engine picks it
    (e.g. +5% of the current rate); the user never has to type a number first.
  - The result has exactly one commit path; no multi-option paralysis.
  - A hopeless trajectory is never shown unprompted: if current behavior never
    reaches the goal, return the SMALLEST delta that does, not the failure curve.
  - ``strain_mode`` (set by Grace, package 05): refuse long-horizon sims and
    return only the single suggested action.

The math is mode-independent; only vocabulary changes with mode. Committing goes
through propose→confirm and records ``WhatIfCommitted``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import Goal as GoalORM
from ...money import cents_to_dollars, dollars_to_cents
from ..goal_math import add_months as _add_months
from ..goal_math import months_to_reach as _months_to_reach
from ..scenario_overlay import GoalMutation, ScenarioOverlay


@dataclass
class WhatIfResult:
    goal_id: int
    goal_name: str
    current_monthly_cents: int
    suggested_delta_cents: int  # the single default delta we recommend
    reaches_on: Optional[str]  # ISO date the goal is reached WITH the delta
    reachable_at_current: bool  # does current behavior ever reach it?
    single_action: bool  # True under strain_mode → only the one action
    commit_label: str

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "goal_name": self.goal_name,
            "current_monthly": cents_to_dollars(self.current_monthly_cents),
            "suggested_delta": cents_to_dollars(self.suggested_delta_cents),
            "reaches_on": self.reaches_on,
            "reachable_at_current": self.reachable_at_current,
            "single_action": self.single_action,
            "commit_label": self.commit_label,
        }


# A non-trivial nudge: 5% of the current rate, floored at $1 so a tiny rate
# still yields a real, reachable suggestion (never +$0).
_DEFAULT_DELTA_PCT = 0.05
_MIN_DELTA_CENTS = 100


class WhatIfService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def simulate(
        self,
        user_id: int,
        goal_id: int,
        *,
        delta_monthly: Optional[float] = None,
        current_monthly: float = 0.0,
        strain_mode: bool = False,
        as_of: Optional[date] = None,
    ) -> WhatIfResult:
        """Compute the default (or supplied) what-if for a goal.

        ``current_monthly`` is the user's existing monthly pace (dollars). If
        ``delta_monthly`` is None we pick the default (reachable, slightly
        better). Under ``strain_mode`` we return only the single suggested
        action and skip any long-horizon date math.
        """
        as_of = as_of or date.today()
        goal = self.db.execute(
            select(GoalORM).where(
                GoalORM.id == goal_id, GoalORM.user_id == user_id
            )
        ).scalar_one()

        remaining_cents = max(goal.amount - (goal.progress or 0), 0)
        current_cents = dollars_to_cents(current_monthly)

        # The default delta: 5% of the current rate, floored at $1 so it is
        # always non-trivial and reachable. Never +$0, never an absurd jump.
        if delta_monthly is not None:
            delta_cents = max(dollars_to_cents(delta_monthly), 0)
        else:
            delta_cents = max(
                int(current_cents * _DEFAULT_DELTA_PCT), _MIN_DELTA_CENTS
            )

        reachable_at_current = current_cents > 0 and remaining_cents >= 0

        # If current behavior never reaches the goal (rate is zero), pick the
        # SMALLEST delta that does reach it within a sane horizon — never show a
        # never-reaches curve. We target reaching within 24 months.
        if current_cents <= 0:
            reachable_at_current = False
            target_months = 24
            needed = -(-remaining_cents // target_months) if remaining_cents else _MIN_DELTA_CENTS
            delta_cents = max(needed, _MIN_DELTA_CENTS)

        if strain_mode:
            # Single-action form: no long-horizon date, just the one suggestion.
            return WhatIfResult(
                goal_id=goal.id,
                goal_name=goal.name,
                current_monthly_cents=current_cents,
                suggested_delta_cents=delta_cents,
                reaches_on=None,
                reachable_at_current=reachable_at_current,
                single_action=True,
                commit_label="commit_single_step",
            )

        # Unify onto the v6 core: the hypothetical is a single goal mutation
        # whose progress is bumped by one month of the (current + delta) pace.
        # The reach date then falls out of the shared goal-math helpers, the
        # SAME ones the scenario evaluate/compare diff uses — one implementation
        # of "how long at this pace, and on what date". Behaviour is unchanged:
        # months-to-reach is still ``remaining / (current + delta)`` ceil'd.
        new_monthly = current_cents + delta_cents
        overlay = ScenarioOverlay(
            goal_mutations=(
                GoalMutation(goal_id=goal.id, amount_cents=goal.amount),
            )
        )
        mutation = overlay.goal_mutations[0]
        target_cents = (
            mutation.amount_cents if mutation.amount_cents is not None else goal.amount
        )
        overlay_remaining = max(target_cents - (goal.progress or 0), 0)
        months = _months_to_reach(overlay_remaining, new_monthly)
        reaches_on = (
            _add_months(as_of, months).isoformat() if months is not None else None
        )

        return WhatIfResult(
            goal_id=goal.id,
            goal_name=goal.name,
            current_monthly_cents=current_cents,
            suggested_delta_cents=delta_cents,
            reaches_on=reaches_on,
            reachable_at_current=reachable_at_current,
            single_action=False,
            commit_label="commit_whatif",
        )
