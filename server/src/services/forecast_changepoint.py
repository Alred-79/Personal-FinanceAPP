"""Stdlib CUSUM change-point detection for spend regimes (F1 stationarity router).

Split-conformal calibration (``forecast_sim``) is only valid on a *stationary*
series; the documented failure mode (docs/FORECAST-BACKTEST.md) is a level/regime
shift in spending — a stretch that is structurally pricier than the trailing
window, which the residual model can't capture because it resamples deviations
from a *fixed* mean burn. This module finds those shifts so the forecast can
truncate its training window to the CURRENT regime (calibrating on the level the
user is actually living in), and so the shift itself — *"grocery spend rose about
$180/mo around Mar 3"* — becomes a user-facing insight the Auditor (F3) and the
game's Grace trigger can read.

Method: **Taylor's CUSUM change-point analysis.** The cumulative sum of deviations
from the series mean drifts steadily when the level shifts; the point of maximum
|CUSUM| is the candidate boundary, and a **permutation bootstrap** (shuffle the
series — a real level shift survives shuffling far less than noise does) gives its
significance. **Binary segmentation** recurses into each side for multiple
change-points.

Deliberately pure stdlib (``random``/``statistics``) and seeded for determinism —
no numpy, no ``ruptures`` (the zero-dep path the roadmap blesses, consistent with
``forecast_sim``'s no-heavy-deps stance). Operates on integer cents; means are the
only floats and stay internal.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass

# Shortest regime we are willing to call, in days. A boundary closer than this to
# either end of a segment is rejected (too little support on one side).
DEFAULT_MIN_SEGMENT = 5
# Permutation resamples for the significance test. 200 is enough for a stable
# 95th-percentile decision and stays cheap on a ~30-point series.
DEFAULT_BOOTSTRAP = 200
# A candidate must beat this share of shuffled series to count as a real shift.
DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class Regime:
    """A contiguous stretch of the series sharing one spend level."""

    start: int  # inclusive index into the series
    end: int  # exclusive
    mean: float  # mean value over [start, end)

    @property
    def length(self) -> int:
        return self.end - self.start


def _cusum(series: list[int]) -> tuple[int, float]:
    """Return ``(boundary_index, s_diff)`` for the CUSUM of mean-deviations.

    ``S_k = Σ_{i<k}(x_i − mean)`` with ``S_0 = S_n = 0``. The boundary candidate
    is the ``k`` maximizing ``|S_k|`` (the split point), and the magnitude is
    Taylor's ``S_diff = max(S) − min(S)``. A flat series gives ``s_diff == 0``.
    """
    n = len(series)
    if n == 0:
        return 0, 0.0
    mean = statistics.fmean(series)
    s = 0.0
    s_max = 0.0
    s_min = 0.0
    best = 0.0
    arg = 0
    for k in range(n):
        s += series[k] - mean
        if abs(s) > best:
            best = abs(s)
            arg = k + 1  # the regime splits AFTER index k
        if s > s_max:
            s_max = s
        if s < s_min:
            s_min = s
    return arg, s_max - s_min


def _is_significant(
    series: list[int],
    observed: float,
    rng: random.Random,
    num_bootstrap: int,
    confidence: float,
) -> bool:
    """Permutation test: a real level shift's ``s_diff`` exceeds that of most
    random shufflings of the same values (which destroy the ordering)."""
    if observed <= 0:
        return False
    shuffled = list(series)
    beat = 0
    for _ in range(num_bootstrap):
        rng.shuffle(shuffled)
        _, s_diff = _cusum(shuffled)
        if s_diff < observed:
            beat += 1
    return (beat / num_bootstrap) >= confidence


def _segment(
    series: list[int],
    offset: int,
    rng: random.Random,
    min_segment: int,
    num_bootstrap: int,
    confidence: float,
    out: list[int],
) -> None:
    """Binary-segmentation worker: find the most significant split, then recurse
    into each side. Appends absolute boundary indices to ``out``."""
    n = len(series)
    if n < 2 * min_segment:
        return
    arg, s_diff = _cusum(series)
    if arg < min_segment or arg > n - min_segment:
        return
    if not _is_significant(series, s_diff, rng, num_bootstrap, confidence):
        return
    out.append(offset + arg)
    _segment(series[:arg], offset, rng, min_segment, num_bootstrap, confidence, out)
    _segment(
        series[arg:], offset + arg, rng, min_segment, num_bootstrap, confidence, out
    )


def detect_changepoints(
    series: list[int],
    *,
    rng: random.Random | None = None,
    min_segment: int = DEFAULT_MIN_SEGMENT,
    num_bootstrap: int = DEFAULT_BOOTSTRAP,
    confidence: float = DEFAULT_CONFIDENCE,
) -> list[int]:
    """Sorted indices where a new regime begins (the first regime is implicit at
    0). Deterministic under a fixed-seed ``rng``."""
    rng = rng or random.Random(0)
    out: list[int] = []
    _segment(
        list(series), 0, rng, min_segment, num_bootstrap, confidence, out
    )
    return sorted(out)


def segment_regimes(
    series: list[int],
    *,
    rng: random.Random | None = None,
    min_segment: int = DEFAULT_MIN_SEGMENT,
    num_bootstrap: int = DEFAULT_BOOTSTRAP,
    confidence: float = DEFAULT_CONFIDENCE,
) -> list[Regime]:
    """Full regime decomposition (≥ 1 regime). The means let callers report the
    size and direction of each shift."""
    if not series:
        return []
    cps = detect_changepoints(
        series,
        rng=rng,
        min_segment=min_segment,
        num_bootstrap=num_bootstrap,
        confidence=confidence,
    )
    bounds = [0, *cps, len(series)]
    regimes: list[Regime] = []
    for a, b in zip(bounds, bounds[1:]):
        if b > a:
            regimes.append(Regime(a, b, statistics.fmean(series[a:b])))
    return regimes


def current_regime_start(
    series: list[int],
    *,
    rng: random.Random | None = None,
    min_segment: int = DEFAULT_MIN_SEGMENT,
    num_bootstrap: int = DEFAULT_BOOTSTRAP,
    confidence: float = DEFAULT_CONFIDENCE,
) -> int:
    """Index at which the most recent regime begins (0 when no shift is found)."""
    cps = detect_changepoints(
        series,
        rng=rng,
        min_segment=min_segment,
        num_bootstrap=num_bootstrap,
        confidence=confidence,
    )
    return cps[-1] if cps else 0
