"""CUSUM change-point detector unit tests (F1 stationarity router).

Deterministic under an injected ``random.Random`` so the bootstrap significance
test is reproducible.
"""

import random

from server.src.services.forecast_changepoint import (
    current_regime_start,
    detect_changepoints,
    segment_regimes,
)


def test_clear_level_shift_is_detected():
    """A step from $1/day to $6/day half-way through is one change-point at the
    step, with the two regime means recovered."""
    series = [100] * 20 + [600] * 20
    cps = detect_changepoints(series, rng=random.Random(0))
    assert cps == [20]
    regimes = segment_regimes(series, rng=random.Random(0))
    assert [(r.start, r.end, round(r.mean)) for r in regimes] == [
        (0, 20, 100),
        (20, 40, 600),
    ]
    assert current_regime_start(series, rng=random.Random(0)) == 20


def test_flat_series_has_no_changepoint():
    assert detect_changepoints([300] * 40, rng=random.Random(0)) == []
    # A single regime spanning the whole series.
    regimes = segment_regimes([300] * 40, rng=random.Random(0))
    assert len(regimes) == 1
    assert current_regime_start([300] * 40, rng=random.Random(0)) == 0


def test_stationary_noise_does_not_false_positive():
    """Pure i.i.d. noise around a fixed mean must NOT be called a regime shift —
    the permutation test is what prevents the band from chasing noise."""
    rng = random.Random(1)
    noise = [max(0, int(rng.gauss(300, 80))) for _ in range(40)]
    assert detect_changepoints(noise, rng=random.Random(0)) == []


def test_multiple_shifts_via_binary_segmentation():
    """Low → high → low recovers BOTH boundaries (binary segmentation recurses
    into each side)."""
    series = [100] * 15 + [700] * 15 + [120] * 15
    cps = detect_changepoints(series, rng=random.Random(0))
    assert len(cps) == 2
    assert 12 <= cps[0] <= 18
    assert 27 <= cps[1] <= 33


def test_detection_is_deterministic_under_seed():
    series = [100] * 20 + [600] * 20
    a = detect_changepoints(series, rng=random.Random(7))
    b = detect_changepoints(series, rng=random.Random(7))
    assert a == b


def test_min_segment_rejects_boundary_too_close_to_edge():
    """A shift in only the last 2 days can't be a 5-day-minimum regime → no
    change-point (avoids truncating to a near-empty window)."""
    series = [100] * 38 + [900] * 2
    assert detect_changepoints(series, rng=random.Random(0), min_segment=5) == []
