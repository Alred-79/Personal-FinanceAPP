"""Shared annotation constants for MCP financial figures.

The ``budget://context`` resource and the ``get_spend_summary`` tool both surface
the spendable allotment, which is easy to misread (it's a HALF, two-week figure
derived only from the most-recent 'Work' paycheck). Keeping the method /
assumptions / caveats text in one place ensures both surfaces describe it
identically, so a consuming LLM can't treat a biweekly half-figure as a monthly
surplus.
"""

from __future__ import annotations

SPENDABLE_METHOD = "spend_service.get_budget_allotment"
SPENDABLE_PERIOD = "P14D"
SPENDABLE_ASSUMPTIONS: list[str] = [
    "Income = the single most-recent paycheck categorized 'Work'; other income ignored",
    "Fixed expenses = recurring expenses, each prorated to a 14-day window",
    "Subtracts savings_percent of the paycheck and prorated active-goal contributions",
    "Result is HALF of remaining income — a two-week figure, NOT monthly",
]
SPENDABLE_CAVEATS: list[str] = [
    "Returns 0 when there is no 'Work' income on record",
    "Not a guaranteed safe-to-spend amount; ignores variable/discretionary spend",
    "A negative value means fixed costs already exceed income for the period — the "
    "user is overspent / over-committed, not under-spent",
    "Overdue, still-unmet goals are excluded from this figure, so it may overstate "
    "what is truly free to spend",
]

# Cashflow forecast — shared by the budget://context resource and the
# get_forecast tool so both describe the projection identically.
FORECAST_METHOD = "forecast_service.forecast (burn-aware + residual-bootstrap)"
FORECAST_ASSUMPTIONS: list[str] = [
    "Starts from the current sum of all account balances",
    "Projects recurring expenses AND recurring income forward over the horizon",
    "Drains an estimated daily discretionary burn (avg of recent non-recurring "
    "spend, top decile dropped) on every day",
    "overdraft_probability and the trough_band come from a residual-bootstrap "
    "simulation that resamples the user's recent daily-spend variation",
]
FORECAST_CAVEATS: list[str] = [
    "The burn estimate needs a few weeks of non-recurring spend; with little "
    "history it is zero and the forecast is scheduled-only",
    "overdraft_probability is a modelled estimate, not a guarantee; treat the "
    "trough_band (low/median/high) as the range of likely outcomes",
    "Accuracy depends on recurrence detection; mislabeled recurrence skews it",
]

# Net worth trend — read-only over the MCP surface.
NETWORTH_METHOD = "networth_service.current_total_cents + balance_snapshots series"
NETWORTH_ASSUMPTIONS: list[str] = [
    "current = live sum of every account balance for the user, right now",
    "series = previously-recorded daily snapshots only; the MCP read path never "
    "writes a new snapshot, so today may be absent until the app records it",
    "Includes liabilities only insofar as they are modelled as negative-balance "
    "accounts; external debts not tracked as accounts are excluded",
]
