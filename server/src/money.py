"""Helpers for moving money between dollars and whole cents.

The database keeps every money value as whole integer cents. The API talks to
callers in dollar floats. These two functions live right at that seam:

* ``dollars_to_cents``: use it on the way in, when a request reaches the DB.
* ``cents_to_dollars``: use it on the way out, when the DB feeds a response.
"""


from decimal import Decimal, ROUND_HALF_EVEN


def dollars_to_cents(dollars: float) -> int:
    """Turn a dollar float into whole cents, rounding ties to the even cent.

    Conversion goes through ``Decimal(str(...))`` so the value the caller typed
    (``10.99``) is what gets scaled, not its inexact binary float (which would
    make e.g. ``round(2.675 * 100)`` land on 267 instead of 268).

    >>> dollars_to_cents(10.99)
    1099
    >>> dollars_to_cents(0)
    0
    """
    cents = Decimal(str(dollars)) * 100
    return int(cents.to_integral_value(rounding=ROUND_HALF_EVEN))


def cents_to_dollars(cents: int) -> float:
    """Turn whole cents back into a dollar float.

    >>> cents_to_dollars(1099)
    10.99
    >>> cents_to_dollars(0)
    0.0
    """
    return cents / 100.0
