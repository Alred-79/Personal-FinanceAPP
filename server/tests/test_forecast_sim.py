"""Residual-bootstrap simulator unit tests.

Deterministic under an injected ``random.Random`` so exact numbers can be frozen.
"""

import random

from server.src.services.forecast_sim import bootstrap_overdraft


def test_empty_residual_pool_collapses_to_deterministic():
    """No residual variation → every run is identical to the point forecast.
    Start $100, $5/day burn, 10 days, no scheduled flows → trough = 100 - 50 =
    $50, never negative."""
    out = bootstrap_overdraft(
        starting_cents=100_00,
        net_by_day_cents={},
        daily_burn_cents=500,
        num_days=10,
        residual_pool_cents=[],
        rng=random.Random(0),
        num_sims=50,
    )
    assert out["overdraft_probability"] == 0.0
    assert out["trough_low"] == out["trough_median"] == out["trough_high"] == 50_00


def test_deterministic_negative_collapses_to_certain_overdraft():
    """Point forecast already dips below zero, no variation → probability 1.0."""
    out = bootstrap_overdraft(
        starting_cents=4_000,  # $40
        net_by_day_cents={},
        daily_burn_cents=500,  # $5/day
        num_days=10,  # drains $50 > $40
        residual_pool_cents=[],
        rng=random.Random(0),
        num_sims=50,
    )
    assert out["overdraft_probability"] == 1.0
    assert out["trough_low"] < 0


def test_band_is_ordered_and_reproducible():
    """With real residual spread the band widens; low <= median <= high, and a
    fixed seed reproduces the exact same numbers run to run."""
    kwargs = dict(
        starting_cents=10_000,
        net_by_day_cents={5: 2_000},  # a small mid-horizon income
        daily_burn_cents=300,
        num_days=10,
        residual_pool_cents=[-200, -100, 0, 100, 200, 500],
        num_sims=200,
    )
    a = bootstrap_overdraft(**kwargs, rng=random.Random(42))
    b = bootstrap_overdraft(**kwargs, rng=random.Random(42))
    assert a == b  # determinism under a fixed seed
    assert a["trough_low"] <= a["trough_median"] <= a["trough_high"]
    assert 0.0 <= a["overdraft_probability"] <= 1.0


def test_zero_days_guard():
    out = bootstrap_overdraft(
        starting_cents=5_000,
        net_by_day_cents={},
        daily_burn_cents=100,
        num_days=0,
        residual_pool_cents=[10],
        rng=random.Random(0),
    )
    assert out["overdraft_probability"] == 0.0
    assert out["trough_median"] == 5_000
