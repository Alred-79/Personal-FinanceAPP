"""The graduation rail (v4 §5.3) + the soft-landing helper.

When a user shows sustained, verified underspend vs. baseline (3+ weeks at the
category level), or repeats the same manual allocation 3+ times, we propose
making it permanent — "make the $30/week sweep standing?" — delivered as a
``GRADUATION`` alert under the same caps. Accepting creates a standing Rule via
propose→confirm.

The **soft-landing principle** (used by packages 09/10, defined here): a failed
or abandoned commitment must NEVER leave state below baseline. ``soft_land``
returns only forward-looking copy and a smaller re-offer — it deducts nothing,
because there is nothing to deduct (no negative/penalty events exist for it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import Rule as RuleORM, RuleExecution as RuleExecutionORM
from ...money import cents_to_dollars

# How long a declined graduation offer is suppressed before re-offering.
DECLINE_COOLDOWN_DAYS = 30
# Manual repeats of the same allocation that trigger a graduation proposal.
REPEAT_THRESHOLD = 3


@dataclass
class GraduationCandidate:
    kind: str  # 'repeat_allocation' | 'sustained_underspend'
    entity: str  # the dedupe key (e.g. "alloc:goal:5")
    amount_cents: int
    cadence: str  # 'weekly' | 'monthly' | ...
    rationale: str  # plain copy; banned-pattern-safe

    def to_proposal(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entity": self.entity,
            "amount": cents_to_dollars(self.amount_cents),
            "cadence": self.cadence,
            "rationale": self.rationale,
        }


def detect_graduation_candidates(
    db: Session, user_id: int, *, as_of: Optional[date] = None
) -> list[GraduationCandidate]:
    """Candidates for a standing-commitment proposal.

    Package 03 implements the repeated-manual-allocation signal (the cleanest to
    verify from existing data): if the same allocation amount fired ≥3 times via
    rule executions, propose making it standing. Sustained-underspend detection
    (category baselines) lands once the stat engine (package 04) provides
    baselines — wired here as a stub returning nothing for now.
    """
    as_of = as_of or date.today()
    candidates: list[GraduationCandidate] = []

    # Repeated allocations: group this user's RuleExecution rows by amount.
    rows = db.execute(
        select(RuleExecutionORM.amount_cents)
        .join(RuleORM, RuleExecutionORM.rule_id == RuleORM.id)
        .where(
            RuleORM.user_id == user_id,
            RuleExecutionORM.action_type == "allocate",
        )
    ).scalars().all()
    counts: dict[int, int] = {}
    for amount in rows:
        counts[amount] = counts.get(amount, 0) + 1
    for amount_cents, n in counts.items():
        if n >= REPEAT_THRESHOLD and amount_cents > 0:
            candidates.append(
                GraduationCandidate(
                    kind="repeat_allocation",
                    entity=f"alloc:{amount_cents}",
                    amount_cents=amount_cents,
                    cadence="weekly",
                    rationale=(
                        f"You've set aside ${cents_to_dollars(amount_cents):.2f} "
                        f"{n} times — make it standing?"
                    ),
                )
            )
    return candidates


def soft_land(contract: dict[str, Any]) -> dict[str, Any]:
    """Wind down an abandoned commitment without penalty.

    Returns ONLY forward-looking copy and a smaller re-offer. It records and
    deducts NOTHING — the soft-landing guarantee is that abandonment never
    leaves the user below baseline. (A test asserts no negative event exists.)
    """
    amount = contract.get("amount", 0.0)
    smaller = round(amount * 0.5, 2)
    return {
        "message": "No problem — nothing lost. Want to try a smaller amount?",
        "re_offer": {"amount": smaller, "cadence": contract.get("cadence", "weekly")},
        "penalty": None,  # there is never a penalty
    }
