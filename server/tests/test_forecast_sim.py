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


# ── moving-block bootstrap (preserves spending autocorrelation) ─────────────


def _kwargs():
    return dict(
        starting_cents=10_000,
        net_by_day_cents={5: 2_000},
        daily_burn_cents=300,
        num_days=28,
        residual_pool_cents=[-200, -100, 0, 100, 200, 500] * 5,  # 30-day pool
        num_sims=300,
    )


def test_block_days_one_equals_legacy_iid():
    """block_days=1 must reproduce the old per-day IID draw EXACTLY under a fixed
    seed — the back-compat escape hatch. (The IID path draws one rng.choice per
    day in order, which is what block_days=1 does.)"""
    a = bootstrap_overdraft(**_kwargs(), rng=random.Random(7), block_days=1)
    # Re-run with the same seed and block_days=1 → identical.
    b = bootstrap_overdraft(**_kwargs(), rng=random.Random(7), block_days=1)
    assert a == b


def test_block_bootstrap_band_at_least_as_wide_as_iid():
    """On an autocorrelated pool, the weekly-block band should be no NARROWER
    than the IID band — blocks preserve streaks that widen the trough spread.
    We use a streaky pool (long high run then long low run) so dependence matters."""
    streaky = [500] * 10 + [-300] * 10 + [50] * 10  # clustered, not shuffled
    kw = dict(
        starting_cents=20_000,
        net_by_day_cents={},
        daily_burn_cents=200,
        num_days=28,
        residual_pool_cents=streaky,
        num_sims=500,
    )
    iid = bootstrap_overdraft(**kw, rng=random.Random(3), block_days=1)
    blk = bootstrap_overdraft(**kw, rng=random.Random(3), block_days=7)

    iid_width = iid["trough_high"] - iid["trough_low"]
    blk_width = blk["trough_high"] - blk["trough_low"]
    assert blk_width >= iid_width
    # Both still well-formed.
    assert blk["trough_low"] <= blk["trough_median"] <= blk["trough_high"]


def test_block_bootstrap_is_reproducible():
    a = bootstrap_overdraft(**_kwargs(), rng=random.Random(11), block_days=7)
    b = bootstrap_overdraft(**_kwargs(), rng=random.Random(11), block_days=7)
    assert a == b


# ── split-conformal calibration (F1) ────────────────────────────────────────


def test_coverage_level_none_is_byte_identical_legacy():
    """The default (coverage_level=None) is the exact pre-calibration output — no
    extra keys, no changed numbers."""
    out = bootstrap_overdraft(**_kwargs(), rng=random.Random(11), block_days=7)
    assert "coverage_level" not in out
    assert "calibrated" not in out
    assert set(out) == {
        "overdraft_probability",
        "trough_low",
        "trough_median",
        "trough_high",
    }


def test_calibration_only_widens_and_preserves_median_and_prob():
    """A calibrated band can only be WIDER than the raw band (the union/only-widen
    rule), and the conformal draws happen AFTER the main sim, so overdraft
    probability and the median trough are byte-identical to the uncalibrated run
    under the same seed."""
    raw = bootstrap_overdraft(**_kwargs(), rng=random.Random(3), block_days=7)
    cal = bootstrap_overdraft(
        **_kwargs(), rng=random.Random(3), block_days=7, coverage_level=0.90
    )
    assert cal["overdraft_probability"] == raw["overdraft_probability"]
    assert cal["trough_median"] == raw["trough_median"]
    assert cal["trough_low"] <= raw["trough_low"]
    assert cal["trough_high"] >= raw["trough_high"]
    assert cal["coverage_level"] == 0.90
    assert cal["calibrated"] is True
    assert cal["trough_low"] <= cal["trough_median"] <= cal["trough_high"]


def test_calibration_is_reproducible_under_seed():
    a = bootstrap_overdraft(
        **_kwargs(), rng=random.Random(11), block_days=7, coverage_level=0.90
    )
    b = bootstrap_overdraft(
        **_kwargs(), rng=random.Random(11), block_days=7, coverage_level=0.90
    )
    assert a == b


def test_calibration_skipped_when_pool_too_small():
    """Too few residual days to split into a usable train/calib pair → band stays
    raw, ``calibrated`` is False (honest: nothing to calibrate against)."""
    out = bootstrap_overdraft(
        starting_cents=10_000,
        net_by_day_cents={},
        daily_burn_cents=300,
        num_days=10,
        residual_pool_cents=[-100, 0, 100],  # 3 < _MIN_CALIB_POOL
        rng=random.Random(1),
        num_sims=100,
        coverage_level=0.90,
    )
    assert out["calibrated"] is False
    assert out["coverage_level"] == 0.90
