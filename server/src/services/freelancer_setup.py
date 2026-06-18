"""W5 — Freelancer onboarding preset (one transactional bootstrap).

Composes the shipped F1 calibrated Safe-to-Spend with the tax layer into the
sharpest market play: "what's safe to spend *and* what to set aside for the IRS"
for 1099 income. One call wires up, **idempotently**:

1. ``User.s2s_horizon = 'month'`` — a freelancer reasons in months, not paychecks.
2. ``settings.tax_features_enabled`` / ``merchant_lifecycle_enabled`` (subscription
   detection) flipped on **in process** if they aren't already (the global ship-dark
   flags; flipping them is the explicit onboarding opt-in).
3. A system **Tax Reserve** ``Goal`` whose target is the tax summary's
   ``annual_estimate_cents`` (falling back to ``safe_harbor_annual_cents``).
4. A C1 ``allocate`` **Rule** that funds the Tax Reserve as self-employment income
   arrives: conditions ``type == income`` AND ``source_type == self_employment``
   (so it can NEVER match an expense or a W-2 paycheck), ``pct`` = the effective
   SE+income tax rate from the summary. Above-threshold fundings PROPOSE (C1/B2).
5. An initial ``income_smoothing`` recommendation (RETURNED, not applied — the
   one-tap accept writes ``User.s2s_buffer`` separately, guardrail B2).

**Idempotency** is by stable identity: the goal is matched by name (``Tax Reserve``)
per user, and the rule by its system name; a second run updates targets/pct in place
and creates nothing new. **Tax-disabled no-op:** when ``tax_features_enabled`` is
False AND we're told not to enable it, the tax steps (goal + rule) are skipped
gracefully — the horizon/smoothing steps still run. Nothing here moves real money.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Goal as GoalORM,
    Rule as RuleORM,
    User as UserORM,
)
from server.src.settings import settings

from .income_smoothing import SmoothingRecommendation, recommend_for_user
from .tax.summary_service import TaxSummaryService

# The system Tax Reserve goal's stable name (its idempotency key per user).
TAX_RESERVE_GOAL_NAME = "Tax Reserve"
# The system reserve rule's stable name.
TAX_RESERVE_RULE_NAME = "Tax Reserve (auto-set-aside)"
# Default freelancer Safe-to-Spend horizon.
FREELANCER_S2S_HORIZON = "month"
# Fallback reserve pct if the summary has no income yet (no division possible). A
# conservative 25% blended SE+income rate — the same crude default the flat-rate
# tax estimate uses — so the rule still does something sane pre-income.
_DEFAULT_RESERVE_PCT = 25.0


@dataclass(frozen=True)
class FreelancerSetupResult:
    """What the preset did. Stable shape for the router/tests."""

    goal_id: Optional[int]
    rule_id: Optional[int]
    reserve_pct: Optional[float]
    reserve_target_cents: Optional[int]
    tax_steps_applied: bool
    s2s_horizon: str
    smoothing: SmoothingRecommendation
    created_goal: bool
    created_rule: bool


def effective_reserve_pct(summary: dict) -> float:
    """The effective SE+income tax rate (percent, 0–100) implied by the estimate.

    ``annual_estimate_cents / total_income_cents`` — the share of gross income the
    two-lane estimate says to set aside. Falls back to the conservative default
    when there is no income yet to divide by. Clamped to [0, 100].
    """
    estimate = summary.get("estimated_quarterly", summary)
    total_income = int(estimate.get("total_income_cents", 0) or 0)
    annual = int(estimate.get("annual_estimate_cents", 0) or 0)
    if total_income <= 0:
        return _DEFAULT_RESERVE_PCT
    pct = annual * 100.0 / total_income
    return max(0.0, min(100.0, round(pct, 2)))


def reserve_target_cents(summary: dict) -> int:
    """The Tax Reserve goal target: the annual estimate, or safe-harbor if present."""
    estimate = summary.get("estimated_quarterly", summary)
    annual = int(estimate.get("annual_estimate_cents", 0) or 0)
    safe_harbor = estimate.get("safe_harbor_annual_cents")
    if annual > 0:
        return annual
    if safe_harbor:
        return int(safe_harbor)
    return 0


def run_preset(
    db: Session,
    user_id: int,
    *,
    tax_year: Optional[int] = None,
    enable_tax_features: bool = True,
    enable_subscription_detection: bool = True,
    today: Optional[date] = None,
) -> FreelancerSetupResult:
    """Run the freelancer onboarding preset for a user (idempotent).

    ``enable_tax_features``: when True (default) the preset flips
    ``settings.tax_features_enabled`` on if needed and builds the Tax Reserve goal +
    rule. When False AND tax features are already off, the tax steps no-op
    gracefully (goal/rule are skipped). ``enable_subscription_detection`` flips the
    merchant-lifecycle flag (subscription detection) similarly.

    Returns a :class:`FreelancerSetupResult`. The smoothing recommendation is
    RETURNED (not applied — B2). Caller commits.
    """
    today = today or date.today()
    tax_year = tax_year or today.year

    user = db.get(UserORM, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")

    # 1. Freelancer Safe-to-Spend horizon (idempotent assignment).
    user.s2s_horizon = FREELANCER_S2S_HORIZON

    # 2. Flip the ship-dark flags on if the caller opted in (process-level).
    if enable_tax_features and not settings.tax_features_enabled:
        settings.tax_features_enabled = True
    if enable_subscription_detection and not settings.merchant_lifecycle_enabled:
        settings.merchant_lifecycle_enabled = True

    tax_active = settings.tax_features_enabled
    goal_id: Optional[int] = None
    rule_id: Optional[int] = None
    pct: Optional[float] = None
    target: Optional[int] = None
    created_goal = False
    created_rule = False

    # 3 + 4. Tax Reserve goal + allocate rule — only when tax features are active.
    if tax_active:
        summary = TaxSummaryService(db).get_tax_summary(user_id, tax_year)
        pct = effective_reserve_pct(summary)
        target = reserve_target_cents(summary)

        goal, created_goal = _ensure_tax_reserve_goal(db, user_id, target, today)
        goal_id = goal.id
        rule, created_rule = _ensure_reserve_rule(db, user_id, goal.id, pct)
        rule_id = rule.id

    # 5. Initial smoothing recommendation (returned, NOT applied — B2).
    smoothing = recommend_for_user(db, user_id)

    db.flush()
    return FreelancerSetupResult(
        goal_id=goal_id,
        rule_id=rule_id,
        reserve_pct=pct,
        reserve_target_cents=target,
        tax_steps_applied=tax_active,
        s2s_horizon=user.s2s_horizon,
        smoothing=smoothing,
        created_goal=created_goal,
        created_rule=created_rule,
    )


def _ensure_tax_reserve_goal(
    db: Session, user_id: int, target_cents: int, today: date
) -> tuple[GoalORM, bool]:
    """Get-or-create the per-user Tax Reserve goal (idempotent by name).

    On a re-run the target is refreshed in place (the estimate moves with income),
    but no second goal is created. Returns ``(goal, created)``. A target of 0 (no
    income yet) is allowed — the goal exists so the rule has somewhere to fund, and
    the target updates on the next run.
    """
    existing = db.execute(
        select(GoalORM).where(
            GoalORM.user_id == user_id,
            GoalORM.name == TAX_RESERVE_GOAL_NAME,
        )
    ).scalar_one_or_none()
    # Reserve "due" is the end of the tax year — a stable, sensible target date.
    due = date(today.year, 12, 31).isoformat()
    if existing is not None:
        existing.amount = int(target_cents)
        # Re-opening a previously-completed reserve when the estimate grows.
        if existing.progress is not None and existing.progress < existing.amount:
            existing.completed = 0
        db.flush()
        return existing, False
    goal = GoalORM(
        user_id=user_id,
        name=TAX_RESERVE_GOAL_NAME,
        description="Set aside for estimated quarterly taxes (1099 income).",
        amount=int(target_cents),
        date=due,
        progress=0,
        completed=0,
    )
    db.add(goal)
    db.flush()
    return goal, True


def _ensure_reserve_rule(
    db: Session, user_id: int, goal_id: int, pct: float
) -> tuple[RuleORM, bool]:
    """Get-or-create the Tax Reserve allocate rule (idempotent by name).

    The conditions REQUIRE both ``type == income`` and
    ``source_type == self_employment`` — so the rule can never fire on an expense
    or on a W-2 paycheck (guardrail / edge case). ``pct`` is the effective SE+income
    rate. On a re-run the pct/target are refreshed in place; no second rule.
    """
    conditions = json.dumps(
        [
            {"field": "type", "op": "eq", "value": "income"},
            {"field": "source_type", "op": "eq", "value": "self_employment"},
        ]
    )
    action_params = json.dumps({"pct": pct})

    existing = db.execute(
        select(RuleORM).where(
            RuleORM.user_id == user_id,
            RuleORM.name == TAX_RESERVE_RULE_NAME,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.conditions = conditions
        existing.action_params = action_params
        existing.target_kind = "goal"
        existing.target_id = goal_id
        existing.enabled = 1
        db.flush()
        return existing, False
    rule = RuleORM(
        user_id=user_id,
        name=TAX_RESERVE_RULE_NAME,
        enabled=1,
        conditions=conditions,
        action_type="allocate",
        action_params=action_params,
        target_kind="goal",
        target_id=goal_id,
        priority=0,
    )
    db.add(rule)
    db.flush()
    return rule, True
