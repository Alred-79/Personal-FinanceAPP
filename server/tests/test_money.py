"""Unit tests for the dollars ↔ cents boundary helpers."""

import pytest
from server.src.money import dollars_to_cents, cents_to_dollars


class TestDollarsToCents:
    def test_normal_amount(self):
        assert dollars_to_cents(10.99) == 1099

    def test_whole_dollars(self):
        assert dollars_to_cents(5.00) == 500

    def test_zero(self):
        assert dollars_to_cents(0) == 0

    def test_negative(self):
        assert dollars_to_cents(-25.50) == -2550

    def test_rounding_half_even(self):
        # Python's round() uses banker's rounding (half to even)
        assert dollars_to_cents(10.995) == 1100  # 0.5 rounds to even → 1100
        assert dollars_to_cents(10.985) == 1098  # 0.5 rounds to even → 1098

    def test_small_fraction(self):
        assert dollars_to_cents(0.01) == 1

    def test_large_amount(self):
        assert dollars_to_cents(999999.99) == 99999999


class TestCentsToDollars:
    def test_normal_amount(self):
        assert cents_to_dollars(1099) == 10.99

    def test_whole_dollars(self):
        assert cents_to_dollars(500) == 5.00

    def test_zero(self):
        assert cents_to_dollars(0) == 0.0

    def test_negative(self):
        assert cents_to_dollars(-2550) == -25.50

    def test_one_cent(self):
        assert cents_to_dollars(1) == 0.01

    def test_large_amount(self):
        assert cents_to_dollars(99999999) == 999999.99


class TestRoundTrip:
    """Verify dollars → cents → dollars preserves the value."""

    @pytest.mark.parametrize(
        "dollars",
        [0, 0.01, 1.00, 10.99, 123.45, -50.00, 999999.99],
    )
    def test_round_trip(self, dollars):
        assert cents_to_dollars(dollars_to_cents(dollars)) == dollars
