"""Regret-monster + Ascension (v4 §8.2, Ascension).

Regret-monster: seeded ONLY from explicit ``worth_it='no'`` tags (never inferred).
>=3 regret tags in a category over a trailing 60 days adds the "regret" aspect —
reflective framing, NEVER punitive. Removing tags below threshold drops it
quietly. Zero XP changes either way.

Ascension: opt-in per-month scoring strictness. STRICTLY a scoring-layer concern —
it changes no budget, alert, target, or sweep. The guarantee is enforced by
keeping all Ascension logic inside the score transform here and nowhere else.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import Account as AccountORM, Expense as ExpenseORM
from ...models import UserInDB

REGRET_TAG_THRESHOLD = 3
REGRET_WINDOW_DAYS = 60

# Punitive words banned from regret templates (reflective framing only).
REGRET_BANNED_WORDS = ("wasted", "shameful", "again", "failed", "stupid")


def category_has_regret_aspect(
    db: Session, user: UserInDB, category: str, as_of: date | None = None
) -> bool:
    """True when >=3 explicit worth_it='no' tags exist in *category* over the
    trailing 60 days. Inference is never used — only the user's own tags."""
    as_of = as_of or date.today()
    cutoff = (as_of - timedelta(days=REGRET_WINDOW_DAYS)).isoformat()
    acct_ids = list(db.execute(
        select(AccountORM.id).where(AccountORM.user_id == user.id)
    ).scalars())
    if not acct_ids:
        return False
    count = db.execute(
        select(func.count(ExpenseORM.id)).where(
            ExpenseORM.account_id.in_(acct_ids),
            ExpenseORM.category == category,
            ExpenseORM.worth_it == "no",
            ExpenseORM.date >= cutoff,
            ExpenseORM.date <= as_of.isoformat(),
        )
    ).scalar_one()
    return int(count or 0) >= REGRET_TAG_THRESHOLD


def regret_lore_line(category: str) -> str:
    """Reflective, never punitive. (The banned-word scan asserts this.)"""
    return f"The Keeper marked several {category} encounters as not worth it."


# ── Ascension — scoring-layer ONLY ──────────────────────────────────────────

# Tier → (weekend discretionary score weight, prestige multiplier bump).
ASCENSION_TIERS = {
    0: {"weekend_weight": 1.0, "prestige_mult": 1.0},
    1: {"weekend_weight": 1.5, "prestige_mult": 1.10},
    2: {"weekend_weight": 1.5, "prestige_mult": 1.20, "objectives_required": True},
}


def apply_ascension_to_score(base_score: float, tier: int) -> float:
    """Apply the Ascension prestige multiplier to a NORMALIZED score. This is the
    ONLY place Ascension touches anything — it never sees or changes budgets,
    alerts, targets, or sweeps."""
    cfg = ASCENSION_TIERS.get(tier, ASCENSION_TIERS[0])
    return round(min(1.0, base_score * cfg["prestige_mult"]), 4)
