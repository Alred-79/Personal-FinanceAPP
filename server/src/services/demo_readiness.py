"""Read-only readiness checks for the public showcase account.

Demo login is intentionally fail-closed: enabling the feature flag is not enough.
The database must have the schema and the minimum coherent seed contract that the
UI depends on.  These checks never migrate, seed, or otherwise mutate data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account,
    BalanceSnapshot,
    Budget,
    Expense,
    Goal,
    Income,
    MerchantAlias,
    Notification,
    Rule,
    Scenario,
    User,
)
from server.src.services.auth_service import DEMO_USERNAME
from server.src.db.rls import set_tenant
from server.src.settings import settings


@dataclass(frozen=True)
class DemoReadiness:
    ready: bool
    state: str
    reason_code: str


_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "users": {"id", "username", "game_mode", "s2s_buffer"},
    "accounts": {"id", "user_id", "balance", "plaid_balance_refreshed_at"},
    "expenses": {"id", "user_id", "account_id", "recurrence"},
    "income": {"id", "user_id", "account_id", "recurrence", "source_type"},
    "budgets": {"id", "user_id", "monthly_limit"},
    "goals": {"id", "user_id", "progress"},
    "rules": {"id", "user_id", "target_kind", "target_id"},
    "rule_executions": {"id", "rule_id", "user_id", "tx_id"},
    "scenarios": {"id", "user_id", "overlay_json"},
    "notifications": {"id", "user_id", "ref"},
    "merchant_aliases": {"id", "user_id", "alias_key", "canonical_key"},
    "balance_snapshots": {"id", "user_id", "date", "total"},
}

DEMO_DATASET_REVISION = "2026-07-23.1"
DEMO_DATASET_MARKER_REF = f"demo:dataset:{DEMO_DATASET_REVISION}"

REQUIRED_GOALS = frozenset({
    "Emergency Fund",
    "House Down Payment",
    "Japan Trip",
    "New Laptop",
    "Tax Reserve",
    "Car Repair Buffer",
    "Camera Kit",
})
REQUIRED_RULES = frozenset({
    "Big purchase heads-up",
    "Round up everyday spending for a home",
    "Set aside 15% of freelance income",
    "Tag Adobe as a tool",
})
REQUIRED_SCENARIOS = frozenset({
    "Add freelance retainer",
    "Lease a creative studio",
})
REQUIRED_BUDGETS = frozenset({
    "Food",
    "Food and Drink",
    "Transportation",
    "Entertainment",
    "Shops",
    "Service",
    "Utilities",
    "Travel",
})

_MINIMUM_COUNTS = {
    Account: 3,
    Expense: 75,
    Income: 12,
    Budget: 8,
    Goal: 6,
    Rule: 3,
    Scenario: 2,
    Notification: 6,
    MerchantAlias: 2,
    BalanceSnapshot: 1,
}

_CONDITION_OPS = {
    "category": {"eq", "in"},
    "amount": {"gt", "lt"},
    "title": {"contains"},
    "account_id": {"eq"},
    "type": {"eq"},
    "source_type": {"eq"},
}


@lru_cache(maxsize=1)
def _expected_alembic_heads() -> frozenset[str]:
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def _schema_is_current(db: Session) -> bool:
    """Require the exact migration head plus the critical demo schema surface."""
    bind = db.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "alembic_version" not in tables:
        return False
    current_heads = frozenset(
        db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    )
    if current_heads != _expected_alembic_heads():
        return False
    if not set(_REQUIRED_COLUMNS).issubset(tables):
        return False
    for table, expected in _REQUIRED_COLUMNS.items():
        actual = {column["name"] for column in inspector.get_columns(table)}
        if not expected.issubset(actual):
            return False
    return True


def _rules_are_engine_valid(db: Session, user_id: int) -> bool:
    rules = db.execute(select(Rule).where(Rule.user_id == user_id)).scalars().all()
    if len(rules) < _MINIMUM_COUNTS[Rule]:
        return False
    for rule in rules:
        if rule.action_type not in {"notify", "allocate", "roundup", "categorize"}:
            return False
        try:
            conditions = json.loads(rule.conditions or "[]")
            params = json.loads(rule.action_params or "{}")
        except (TypeError, ValueError):
            return False
        if not isinstance(conditions, list) or not isinstance(params, dict):
            return False
        for condition in conditions:
            if not isinstance(condition, dict):
                return False
            if condition.get("op") not in _CONDITION_OPS.get(condition.get("field"), set()):
                return False
        if rule.action_type in {"allocate", "roundup"}:
            if rule.target_kind != "goal" or rule.target_id is None:
                return False
            target_exists = db.execute(
                select(Goal.id).where(Goal.id == rule.target_id, Goal.user_id == user_id)
            ).scalar_one_or_none()
            if target_exists is None:
                return False
    return True


def _canonical_seed_is_intact(db: Session, user_id: int) -> bool:
    """Check identity-bearing rows that visitor mutations must not erase."""
    names = lambda model, column: frozenset(
        db.execute(select(column).where(model.user_id == user_id)).scalars().all()
    )
    if not REQUIRED_GOALS.issubset(names(Goal, Goal.name)):
        return False
    if not REQUIRED_RULES.issubset(names(Rule, Rule.name)):
        return False
    if not REQUIRED_SCENARIOS.issubset(names(Scenario, Scenario.name)):
        return False
    if not REQUIRED_BUDGETS.issubset(names(Budget, Budget.category)):
        return False
    marker = db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.ref == DEMO_DATASET_MARKER_REF,
        )
    ).scalar_one_or_none()
    if marker is None:
        return False

    visible_total = db.execute(
        select(func.coalesce(func.sum(Account.balance), 0)).where(
            Account.user_id == user_id
        )
    ).scalar_one()
    latest = db.execute(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.user_id == user_id)
        .order_by(BalanceSnapshot.date.desc(), BalanceSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return latest is not None and int(latest.total) == int(visible_total)


def assess_demo_readiness(db: Session, *, enabled: bool) -> DemoReadiness:
    """Return the public readiness state without changing schema or seed data."""
    if not enabled:
        return DemoReadiness(False, "disabled", "demo_disabled")
    try:
        if not _schema_is_current(db):
            return DemoReadiness(False, "unavailable", "schema_outdated")

        user = db.execute(
            select(User).where(User.username == DEMO_USERNAME)
        ).scalar_one_or_none()
        if user is None:
            return DemoReadiness(False, "unavailable", "seed_missing")
        if user.disabled:
            return DemoReadiness(False, "unavailable", "demo_disabled_user")
        if user.game_mode != "off":
            return DemoReadiness(False, "unavailable", "seed_incomplete")

        # The public auth router runs before the normal authenticated
        # ``get_tenant_db`` dependency. On FORCE-RLS Postgres, every showcase
        # table therefore fails closed until we bind the known demo tenant in
        # this same transaction. ``SET LOCAL`` cannot leak through the pool and
        # all subsequent count/rule/target reads are scoped to this one user.
        if settings.enable_rls:
            set_tenant(db, user.id)

        for model, minimum in _MINIMUM_COUNTS.items():
            count = db.execute(
                select(func.count(model.id)).where(model.user_id == user.id)
            ).scalar_one()
            if count < minimum:
                return DemoReadiness(False, "unavailable", "seed_incomplete")

        tax_reserve = db.execute(
            select(Goal.id).where(
                Goal.user_id == user.id,
                Goal.name == "Tax Reserve",
                Goal.completed == 0,
            )
        ).scalar_one_or_none()
        if (
            tax_reserve is None
            or not _rules_are_engine_valid(db, user.id)
            or not _canonical_seed_is_intact(db, user.id)
        ):
            return DemoReadiness(False, "unavailable", "seed_incomplete")
    except (SQLAlchemyError, KeyError, TypeError, ValueError):
        # Public status should remain reachable even with an old/partial schema.
        db.rollback()
        return DemoReadiness(False, "unavailable", "database_unavailable")

    return DemoReadiness(True, "ready", "ready")
