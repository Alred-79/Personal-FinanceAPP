"""Property-based tests for the money seam (``server/src/money.py``).

Example-based tests pin specific values; these assert the *invariants* that must
hold across the whole input space — the kind of edge case (large balances, many
decimals, ties) that hand-picked examples miss. See the code-audit §Testing note
on property-based testing for money/serialization invariants (Hypothesis).
"""

from decimal import Decimal, ROUND_HALF_EVEN

from hypothesis import given, strategies as st

from server.src.money import (
    cents_to_dollars,
    dollars_to_cents,
    round_half_even_cents,
)

# Dollar amounts a real account can hold: bounded, at most 2 decimal places (the
# API contract — callers send cent-precision dollars). allow_nan/inf off.
cent_dollars = st.integers(min_value=-1_000_000_000, max_value=1_000_000_000).map(
    lambda c: c / 100.0
)


@given(cent_dollars)
def test_dollars_cents_round_trip(dollars):
    """A cent-precision dollar amount survives a dollars→cents→dollars round trip
    exactly. This is the core seam guarantee the whole app relies on."""
    cents = dollars_to_cents(dollars)
    assert isinstance(cents, int)
    assert cents_to_dollars(cents) == dollars


@given(cent_dollars)
def test_dollars_to_cents_matches_banker_rounding(dollars):
    """``dollars_to_cents`` equals the Decimal banker's-rounding reference — no
    binary-float drift (the ``Decimal(str(...))`` guarantee in the docstring)."""
    expected = int((Decimal(str(dollars)) * 100).to_integral_value(ROUND_HALF_EVEN))
    assert dollars_to_cents(dollars) == expected


@given(st.integers(min_value=-1_000_000_000, max_value=1_000_000_000))
def test_cents_to_dollars_is_left_inverse(cents):
    """Whole cents → dollars → whole cents is the identity (no precision loss for
    any integer-cent value in range)."""
    assert dollars_to_cents(cents_to_dollars(cents)) == cents


@given(cent_dollars, cent_dollars)
def test_dollars_to_cents_is_monotonic(a, b):
    """Order-preserving: a larger dollar amount never converts to fewer cents."""
    if a <= b:
        assert dollars_to_cents(a) <= dollars_to_cents(b)


@given(st.floats(min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False))
def test_round_half_even_cents_within_half_cent(value):
    """Rounding a fractional-cent quantity lands within half a unit of the input
    and equals the Decimal banker's-rounding reference."""
    result = round_half_even_cents(value)
    assert isinstance(result, int)
    assert abs(result - Decimal(str(value))) <= Decimal("0.5")
    expected = int(Decimal(str(value)).to_integral_value(ROUND_HALF_EVEN))
    assert result == expected
