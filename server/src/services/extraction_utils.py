"""Pure parse helpers shared by every document-extraction path.

Receipt scanning, statement reconciliation, and the generic "import anything"
extractor all face the same small problem: a vision/text model hands back an
``amount`` and a ``date`` in whatever shape it pleased ("$1,234.50", "1234.5",
"03/14/2026", "March 14, 2026"), and we need a clean number and an ISO date —
or a clear ``None`` when it's unreadable, so the row surfaces for review rather
than importing garbage.

These two functions started life inside ``receipt_service`` and are lifted here
so the newer extractors can reuse them without importing across services. They
are pure (no DB, no network) and unit-tested directly.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Optional

# Reject any extracted amount whose magnitude exceeds the API's money bound
# (server/src/models.py _MONEY: ±1e12). A model/statement can emit absurd figures
# (1e308, NaN); without this they'd be written straight to the ORM as cents,
# bypassing the Pydantic _MONEY bound the API enforces. Rejected → None → the
# caller's exception-row branch (E2).
_MAX_ABS_AMOUNT = 1_000_000_000_000  # 1e12, matching _MONEY's ge/le


def parse_amount(value: Any) -> Optional[float]:
    """Coerce a model-supplied amount to a 2dp float, or None if unreadable.

    Accepts a number as-is, or strips currency symbols / thousands separators
    from a string ("$1,234.50" → 1234.5). Returns None for empty / non-numeric
    input — and for a non-finite or out-of-range magnitude (E2) — so the caller
    can flag the row instead of inventing or importing a value.

    >>> parse_amount("$1,234.50")
    1234.5
    >>> parse_amount(None) is None
    True
    >>> parse_amount(1e308) is None
    True
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; never an amount
        return None
    if isinstance(value, (int, float)):
        return _bounded(float(value))
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return _bounded(float(cleaned))
    except ValueError:
        return None


def _bounded(v: float) -> Optional[float]:
    """Round to 2dp, or None when non-finite / beyond the money bound (E2)."""
    if not math.isfinite(v) or abs(v) > _MAX_ABS_AMOUNT:
        return None
    return round(v, 2)


def parse_date(value: Any) -> Optional[str]:
    """Coerce a model-supplied date to ISO ``YYYY-MM-DD``, or None if unreadable.

    Tries the formats bank documents and receipts actually use. Returns None
    rather than guessing when nothing matches.

    >>> parse_date("03/14/2026")
    '2026-03-14'
    >>> parse_date("garbage") is None
    True
    """
    if not value:
        return None
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None
