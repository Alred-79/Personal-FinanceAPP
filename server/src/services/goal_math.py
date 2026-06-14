"""Shared goal-reach date math (v6 doc 04).

Promoted out of ``server.src.services.game.whatif`` so both the what-if engine
and the scenario evaluate/compare diff share ONE implementation of "how long to
reach a goal at a given monthly pace, and on what date". Pure, DB-free, in cents.

``whatif.py`` re-exports these for backwards compatibility; its tests stay green.
"""

from __future__ import annotations

from datetime import date
from typing import Optional


def months_to_reach(remaining_cents: int, monthly_cents: int) -> Optional[int]:
    """Whole months to cover *remaining* at *monthly*, or ``None`` if monthly ≤ 0.

    Ceil division: a partial final month still counts as a whole month.

    >>> months_to_reach(1000, 300)
    4
    >>> months_to_reach(1000, 0) is None
    True
    """
    if monthly_cents <= 0:
        return None
    return -(-remaining_cents // monthly_cents)  # ceil division


def add_months(start: date, months: int) -> date:
    """The first of the month *months* after *start* (calendar-correct rollover).

    >>> add_months(date(2026, 11, 15), 3)
    datetime.date(2027, 2, 1)
    """
    m = start.month - 1 + months
    year = start.year + m // 12
    month = m % 12 + 1
    return date(year, month, 1)
