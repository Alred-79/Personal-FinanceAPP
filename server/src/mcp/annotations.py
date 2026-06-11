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
