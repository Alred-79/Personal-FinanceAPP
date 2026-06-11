"""MCP context resource — annotated financial snapshot.

``ContextBuilder(db).build(uid)`` assembles a single read-only snapshot where every
computed figure ships with its method, assumptions, and caveats.  This prevents a
consuming LLM from misrepresenting a biweekly half-figure as "monthly surplus" or an
expenses-only forecast as "when the user runs out of money."

This module is deliberately DB-free (the import guard enforces this).  It receives
an open session from the vault and delegates to the shared service layer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from server.src.mcp.annotations import (
    SPENDABLE_ASSUMPTIONS as _SPENDABLE_ASSUMPTIONS,
    SPENDABLE_CAVEATS as _SPENDABLE_CAVEATS,
    SPENDABLE_METHOD as _SPENDABLE_METHOD,
    SPENDABLE_PERIOD as _SPENDABLE_PERIOD,
)
from server.src.services.budget_service import BudgetService
from server.src.services.forecast_service import ForecastService
from server.src.services.read_queries import query_goals, query_user
from server.src.services.spend_service import SpendService
from server.src.settings import settings

SCHEMA_VERSION = "1.0"

# Compose-by-scope (least-privilege): the context resource includes a section only
# when the requesting key holds the matching granular scope.  When ``build`` is
# called with ``scopes=None`` (e.g. internal/full snapshot), every section is
# included for backward compatibility.
_SECTION_SCOPES = {
    "spendable": "read:budgets",        # income-derived
    "cashflow_forecast": "read:accounts",  # balances
    "budgets": "read:budgets",
    "goals": "read:goals",
}

# Annotation constants for the spendable figure are shared with get_spend_summary
# (imported above from server.src.mcp.annotations) so both surfaces describe it
# identically.

# ---------------------------------------------------------------------------
# Annotation constants — cashflow forecast
# ---------------------------------------------------------------------------

_FORECAST_METHOD = "forecast_service.forecast"
_FORECAST_ASSUMPTIONS: list[str] = [
    "Projects ONLY recurring expenses; no income is projected forward",
    "Starts from the current sum of all account balances",
    "One-off / non-recurring future expenses are not included",
]
_FORECAST_CAVEATS: list[str] = [
    "Deliberately pessimistic — real balance is usually higher because income isn't modeled",
    "Accuracy depends on recurrence detection; mislabeled recurrence skews it",
]

# ---------------------------------------------------------------------------
# Annotation constants — budgets
# ---------------------------------------------------------------------------

_BUDGETS_METHOD = "budget_service.summarize"
_BUDGETS_ASSUMPTIONS: list[str] = [
    "'This month' = the calendar month containing today",
    "effective_limit folds in prior-month rollover surplus when rollover is on",
    "prorated_target = linear allowance for days elapsed this month",
]

# ---------------------------------------------------------------------------
# Annotation constants — goals
# ---------------------------------------------------------------------------

_GOALS_METHOD = "read_queries.query_goals"
_GOALS_ASSUMPTIONS: list[str] = [
    "Includes all goals for the authenticated user regardless of completion status",
    "feasibility is reserved as null in v1; will add required_per_period and available_per_period",
]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class ContextBuilder:
    """Assemble the annotated financial snapshot for a given user."""

    def __init__(self, db) -> None:
        self._db = db

    def build(
        self, uid: int, scopes: frozenset[str] | None = None
    ) -> dict[str, Any]:
        """Assemble the snapshot, gating each section by *scopes*.

        ``scopes=None`` includes every section (full internal snapshot); when a
        scope set is supplied, a section the key is not scoped for is replaced by
        a ``{"available": False, "required_scope": ...}`` stub so the schema keys
        stay stable and the consuming LLM knows the data exists but was not
        granted.
        """
        today = date.today()
        now_utc = datetime.now(timezone.utc)

        def _gated(section: str, builder):
            if scopes is None or _SECTION_SCOPES[section] in scopes:
                return builder()
            return {"available": False, "required_scope": _SECTION_SCOPES[section]}

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_utc.isoformat(),
            "currency": "USD",
            "spendable": _gated("spendable", lambda: self._build_spendable(uid)),
            "cashflow_forecast": _gated(
                "cashflow_forecast", lambda: self._build_forecast(uid, today)
            ),
            "budgets": _gated("budgets", lambda: self._build_budgets(uid, today)),
            "goals": _gated("goals", lambda: self._build_goals(uid)),
            "baselines": None,
        }

    # -- section builders --------------------------------------------------

    def _build_spendable(self, uid: int) -> dict[str, Any]:
        user = query_user(self._db, uid)
        value = SpendService(self._db).get_budget_allotment(user) if user else 0.0
        return {
            "value": value,
            "unit": "USD",
            "period": _SPENDABLE_PERIOD,
            "method": _SPENDABLE_METHOD,
            "assumptions": _SPENDABLE_ASSUMPTIONS,
            "caveats": _SPENDABLE_CAVEATS,
        }

    def _build_forecast(self, uid: int, today: date) -> dict[str, Any]:
        horizon_days = settings.mcp_context_forecast_days
        horizon_end = today + timedelta(days=horizon_days)
        raw = ForecastService(self._db).forecast(uid, today, horizon_end)
        return {
            "horizon": {
                "start": raw["horizon_start"],
                "end": raw["horizon_end"],
                "days": horizon_days,
            },
            "starting_balance": raw["starting_balance"],
            "ending_balance": raw["ending_balance"],
            "lowest_balance": {
                "value": raw["lowest_balance"],
                "date": raw["lowest_date"],
            },
            "will_go_negative": raw["will_go_negative"],
            "method": _FORECAST_METHOD,
            "assumptions": _FORECAST_ASSUMPTIONS,
            "caveats": _FORECAST_CAVEATS,
        }

    def _build_budgets(self, uid: int, today: date) -> dict[str, Any]:
        raw = BudgetService(self._db).summarize(uid)
        categories = [
            {
                "category": b["category"],
                "monthly_limit": b["monthly_limit"],
                "effective_limit": b["effective_limit"],
                "spent": b["spent"],
                "remaining": b["remaining"],
                "prorated_target": b["prorated_target"],
                "rollover": b["rollover"],
                "over_budget": b["over_budget"],
                "on_pace": b["on_pace"],
            }
            for b in raw
        ]
        return {
            "as_of": today.isoformat(),
            "scope": "month-to-date",
            "method": _BUDGETS_METHOD,
            "assumptions": _BUDGETS_ASSUMPTIONS,
            "categories": categories,
        }

    def _build_goals(self, uid: int) -> dict[str, Any]:
        raw = query_goals(self._db, uid)
        items = [
            {
                "name": g["name"],
                "target_amount": g["amount"],
                "progress": g["progress"],
                "remaining": round(g["amount"] - g["progress"], 2),
                "target_date": g["date"],
                "completed": g["completed"],
                "feasibility": None,
            }
            for g in raw
        ]
        return {
            "method": _GOALS_METHOD,
            "assumptions": _GOALS_ASSUMPTIONS,
            "items": items,
        }
