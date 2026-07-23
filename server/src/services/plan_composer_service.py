"""Deterministic, non-persistable soft-allocation preview drafts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import Goal, User
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.services.auth_service import _to_user_in_db
from server.src.services.scenario_overlay import GoalMutation, ScenarioOverlay
from server.src.services.scenario_service import ScenarioService
from server.src.services.spend_service import SpendService


class PlanComposerError(ValueError):
    pass


@dataclass(frozen=True)
class _Goal:
    id: int
    name: str
    progress: int
    capacity: int
    deadline: str


def _deadline_alloc(total: int, goals: list[_Goal]) -> tuple[dict[int, int], int]:
    left = total
    out: dict[int, int] = {}
    for goal in sorted(goals, key=lambda g: (g.deadline or "9999-12-31", g.id)):
        amount = min(left, goal.capacity)
        if amount:
            out[goal.id] = amount
        left -= amount
        if left == 0:
            break
    return out, left


def _balanced_alloc(total: int, goals: list[_Goal]) -> tuple[dict[int, int], int]:
    """Cent-exact capped equal allocation with deterministic remainder order."""
    ordered = sorted(goals, key=lambda g: (g.deadline or "9999-12-31", g.id))
    left = total
    out = {goal.id: 0 for goal in ordered}
    active = [goal for goal in ordered if goal.capacity > 0]
    while left > 0 and active:
        base, remainder = divmod(left, len(active))
        if base == 0:
            for goal in active[:remainder]:
                out[goal.id] += 1
                left -= 1
            break
        spent = 0
        next_active: list[_Goal] = []
        for index, goal in enumerate(active):
            room = goal.capacity - out[goal.id]
            want = base + (1 if index < remainder else 0)
            take = min(room, want)
            out[goal.id] += take
            spent += take
            if out[goal.id] < goal.capacity:
                next_active.append(goal)
        if spent == 0:
            break
        left -= spent
        active = next_active
    return {gid: amount for gid, amount in out.items() if amount}, left


class PlanComposerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _goals(self, user_id: int, requested: list[int]) -> list[_Goal]:
        ids = list(dict.fromkeys(requested))
        if not ids:
            return []
        rows = self.db.execute(select(Goal).where(Goal.id.in_(ids))).scalars().all()
        by_id = {row.id: row for row in rows}
        if set(by_id) != set(ids):
            raise PlanComposerError("A selected goal is missing or unavailable.")
        if any(row.user_id != user_id for row in rows):
            raise PlanComposerError("A selected goal is missing or unavailable.")
        if any(bool(row.completed) for row in rows):
            raise PlanComposerError("Completed goals cannot be included in a preview.")
        return [
            _Goal(
                id=row.id,
                name=row.name,
                progress=max(0, int(row.progress or 0)),
                capacity=max(0, int(row.amount or 0) - int(row.progress or 0)),
                deadline=row.date or "",
            )
            for row in rows
        ]

    def compose(
        self,
        user_id: int,
        *,
        max_allocation_cents: int,
        additional_buffer_cents: int,
        goal_ids: list[int],
        priority: str = "balanced",
        horizon_days: int = 90,
        as_of: date | None = None,
    ) -> dict:
        if priority not in {"buffer", "balanced", "deadlines"}:
            raise PlanComposerError("Unknown priority.")
        if max_allocation_cents < 0 or additional_buffer_cents < 0:
            raise PlanComposerError("Amounts cannot be negative.")
        user = self.db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user is None:
            raise PlanComposerError("Owner not found.")
        goals = self._goals(user_id, goal_ids)
        as_of = as_of or date.today()
        baseline = SpendService(self.db).safe_to_spend(
            _to_user_in_db(user), as_of, include_outlook=False
        )
        baseline_available_cents = dollars_to_cents(baseline["available"])
        baseline_cap = max(0, baseline_available_cents)
        total = min(max_allocation_cents, baseline_cap)
        requested_buffer = min(additional_buffer_cents, total)
        current_buffer = int(user.s2s_buffer or 0)

        candidates: list[tuple[str, str, int, dict[int, int], int]] = []

        # Buffer-forward: requested floor first, then remaining cents by deadline.
        buffer_delta = requested_buffer
        goal_alloc, left = _deadline_alloc(total - buffer_delta, goals)
        candidates.append(("Buffer-forward", "buffer", buffer_delta, goal_alloc, left))

        # Even split: half toward the requested floor, balance equally across goals.
        balanced_buffer = min(requested_buffer, total // 2 if goals else total)
        goal_alloc, left = _balanced_alloc(total - balanced_buffer, goals)
        if left and balanced_buffer < requested_buffer:
            extra = min(left, requested_buffer - balanced_buffer)
            balanced_buffer += extra
            left -= extra
        candidates.append(("Even split", "balanced", balanced_buffer, goal_alloc, left))

        # Deadline order: goal capacity first, then the requested floor.
        goal_alloc, left = _deadline_alloc(total, goals)
        deadline_buffer = min(left, requested_buffer)
        left -= deadline_buffer
        candidates.append(("Deadline order", "deadlines", deadline_buffer, goal_alloc, left))

        order = {"buffer": 1, "balanced": 2, "deadlines": 3}
        order[priority] = 0
        candidates.sort(key=lambda item: (order.get(item[1], 4), item[0]))
        seen: set[tuple] = set()
        drafts: list[dict] = []
        goal_by_id = {goal.id: goal for goal in goals}
        for name, kind, buffer_delta, allocations, unallocated in candidates:
            signature = (buffer_delta, tuple(sorted(allocations.items())))
            if signature in seen:
                continue
            seen.add(signature)
            mutations = tuple(
                GoalMutation(
                    goal_id=goal_id,
                    progress_cents=goal_by_id[goal_id].progress + amount,
                )
                for goal_id, amount in sorted(allocations.items())
            )
            overlay = ScenarioOverlay(
                goal_mutations=mutations,
                config_overrides={"s2s_buffer": current_buffer + buffer_delta},
            )
            evaluation = ScenarioService(self.db).evaluate(
                user_id,
                overlay,
                as_of=as_of,
                horizon_days=horizon_days,
                rng=random.Random(0),
                name=name,
            )
            allocated = buffer_delta + sum(allocations.values())
            drafts.append(
                {
                    "name": name,
                    "method": kind,
                    "allocation": {
                        "total": cents_to_dollars(allocated),
                        "unallocated": cents_to_dollars(total - allocated),
                        "buffer_floor": {
                            "current": cents_to_dollars(current_buffer),
                            "delta": cents_to_dollars(buffer_delta),
                            "proposed": cents_to_dollars(current_buffer + buffer_delta),
                        },
                        "goals": [
                            {
                                "goal_id": goal_id,
                                "name": goal_by_id[goal_id].name,
                                "current_progress": cents_to_dollars(goal_by_id[goal_id].progress),
                                "delta": cents_to_dollars(amount),
                                "proposed_progress": cents_to_dollars(
                                    goal_by_id[goal_id].progress + amount
                                ),
                            }
                            for goal_id, amount in sorted(allocations.items())
                        ],
                    },
                    "evaluation": evaluation,
                    "assumptions": [
                        "Soft labels only; no money moves.",
                        "The buffer is a spending floor, not a funded reserve.",
                        "Safe-to-Spend is recomputed by the model; it is not assumed to fall by the nominal allocation.",
                    ],
                }
            )
        return {
            "persistable": False,
            "disclosure": "Soft labels only—nothing moves.",
            "requested_max": cents_to_dollars(max_allocation_cents),
            "baseline_non_negative_cap": cents_to_dollars(baseline_cap),
            "amount_modeled": cents_to_dollars(total),
            "drafts": drafts,
        }
