"""Helpers for parsing the ISO ``YYYY-MM-DD`` dates the app stores as strings.

Dates live in the DB as ``YYYY-MM-DD`` text. Several call sites need to turn one
back into a ``date``, and they all share the same strict parse. They differ only
in what they do with a bad value — raise, skip, or return ``None`` — so this module
owns the parse and each caller keeps its own policy on top of it.
"""

from datetime import date, datetime


def parse_iso_date(value: str) -> date | None:
    """Parse a strict ``YYYY-MM-DD`` string into a ``date``.

    Returns ``None`` for anything that isn't a valid ``YYYY-MM-DD`` value
    (including ``None`` or a non-string), so callers can choose to raise, skip,
    or substitute as they see fit.

    >>> parse_iso_date("2026-01-31")
    datetime.date(2026, 1, 31)
    >>> parse_iso_date("not-a-date") is None
    True
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
