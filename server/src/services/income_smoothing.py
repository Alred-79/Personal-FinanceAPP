"""W5 — self-employment income smoothing (pure, seeded).

A 1099 earner's income is lumpy: a $9k month, then a $1k month. Safe-to-Spend
should not swing with it. This service measures the *dispersion* of a freelancer's
**self-employment** monthly income over a trailing window and recommends an
``s2s_buffer`` (integer cents) large enough to smooth a target-percentile **low**
month — i.e. how much of a good month to hold back so a typical bad month still
clears the average.

Method (mirrors the bootstrap-residual idea in ``forecast_sim``): treat each
month's deviation from the trailing **mean** monthly income as a residual; resample
those residuals with a **seeded** ``random.Random`` to estimate the distribution of
a single month's shortfall below the mean; the recommended buffer is the magnitude
of the target-percentile (default 20th → a "1-in-5 bad month") shortfall. A flat
income series has ~zero dispersion, so the recommended buffer is ~0 (the explicit
edge case the tests pin).

Pure and dependency-free (stdlib ``random``/``statistics`` only) so it is fully
deterministic under the injected seed. All money is integer cents; only
``self_employment`` income contributes (W-2 / other / NULL rows are ignored — the
reserve and smoothing never touch a salaried paycheck). Applying a recommendation
(writing ``User.s2s_buffer``) is a SEPARATE, one-tap step — this module only
RECOMMENDS (guardrail B2).
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import Account as AccountORM, Income as IncomeORM

# Trailing window (months) of self-employment income the recommendation reads.
DEFAULT_WINDOW_MONTHS = 12
# Default target percentile (0–1) of the shortfall distribution the buffer covers.
# 0.20 → smooth a "1-in-5" bad month (the 20th-percentile low month).
DEFAULT_TARGET_PERCENTILE = 0.20
# Number of bootstrap resamples — enough for a stable low percentile, cheap.
DEFAULT_NUM_SAMPLES = 500
# Fixed seed so the same series always yields the same buffer (guardrail B5).
DEFAULT_SEED = 1099
# Below this many distinct months of self-employment income we can't measure
# dispersion meaningfully, so we recommend a 0 buffer and say so.
_MIN_MONTHS = 3


@dataclass(frozen=True)
class SmoothingRecommendation:
    """A one-tap buffer recommendation. ``applied`` is always False here — applying
    it (writing ``User.s2s_buffer``) is the separate confirm step (B2)."""

    recommended_buffer_cents: int
    months_observed: int
    mean_monthly_cents: int
    target_percentile: float
    sufficient_data: bool
    rationale: str
    applied: bool = False


def _percentile_sorted(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile of an already-sorted list (q in [0, 1])."""
    if not sorted_vals:
        return 0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = round(q * (len(sorted_vals) - 1))
    return sorted_vals[idx]


def monthly_self_employment_income_cents(
    db: Session, user_id: int, *, window_months: int = DEFAULT_WINDOW_MONTHS
) -> dict[str, int]:
    """Sum ``self_employment`` income per calendar month (``YYYY-MM``) for a user.

    Reads the trailing ``window_months`` distinct months present in the data (most
    recent first), so a sparse history just yields fewer months. Only rows whose
    ``source_type == 'self_employment'`` count — W-2 / other / NULL are excluded.
    Integer cents throughout.
    """
    rows = db.execute(
        select(IncomeORM.date, IncomeORM.amount)
        .join(AccountORM, IncomeORM.account_id == AccountORM.id)
        .where(
            AccountORM.user_id == user_id,
            IncomeORM.source_type == "self_employment",
        )
    ).all()

    by_month: dict[str, int] = defaultdict(int)
    for date_str, amount_cents in rows:
        month = str(date_str)[:7]  # 'YYYY-MM'
        if len(month) != 7:
            continue
        by_month[month] += abs(int(amount_cents))

    # Keep only the most recent ``window_months`` months.
    months = sorted(by_month, reverse=True)[:window_months]
    return {m: by_month[m] for m in sorted(months)}


def monthly_income_cents_by_type(
    db: Session, user_id: int, *, window_months: int = DEFAULT_WINDOW_MONTHS
) -> dict[str, dict[str, int]]:
    """Income per calendar month split into ``self_employment`` / ``w2`` / ``total``.

    Like ``monthly_self_employment_income_cents`` but keeps EVERY income row and
    buckets by ``source_type``: ``self_employment`` rows count to the SE bucket,
    everything else (w2 / other / NULL) folds into ``w2`` (the non-SE bucket).
    This powers the income-volatility dispersion plot's W-2-vs-SE split. Returns
    the trailing ``window_months`` months, oldest→newest. Integer cents.
    """
    rows = db.execute(
        select(IncomeORM.date, IncomeORM.amount, IncomeORM.source_type)
        .join(AccountORM, IncomeORM.account_id == AccountORM.id)
        .where(AccountORM.user_id == user_id)
    ).all()

    by_month: dict[str, dict[str, int]] = defaultdict(
        lambda: {"self_employment": 0, "w2": 0, "total": 0}
    )
    for date_str, amount_cents, source_type in rows:
        month = str(date_str)[:7]  # 'YYYY-MM'
        if len(month) != 7:
            continue
        amt = abs(int(amount_cents))
        bucket = "self_employment" if source_type == "self_employment" else "w2"
        by_month[month][bucket] += amt
        by_month[month]["total"] += amt

    months = sorted(by_month, reverse=True)[:window_months]
    return {m: dict(by_month[m]) for m in sorted(months)}


def recommend_buffer(
    monthly_income_cents: list[int],
    *,
    target_percentile: float = DEFAULT_TARGET_PERCENTILE,
    seed: int = DEFAULT_SEED,
    num_samples: int = DEFAULT_NUM_SAMPLES,
) -> SmoothingRecommendation:
    """Recommend an ``s2s_buffer`` (cents) from a list of monthly SE income totals.

    Pure + seeded. Computes each month's residual against the trailing **mean**,
    bootstrap-resamples those residuals under a fixed seed to estimate a single
    month's shortfall distribution, and returns the magnitude of the
    ``target_percentile`` (low) shortfall as the buffer. A flat series (all months
    equal) has zero residual spread, so the buffer is 0.
    """
    months = [int(m) for m in monthly_income_cents]
    n = len(months)
    if n < _MIN_MONTHS:
        return SmoothingRecommendation(
            recommended_buffer_cents=0,
            months_observed=n,
            mean_monthly_cents=(sum(months) // n) if n else 0,
            target_percentile=target_percentile,
            sufficient_data=False,
            rationale=(
                f"Only {n} month(s) of self-employment income — need "
                f"{_MIN_MONTHS}+ to measure how lumpy it is. No buffer recommended yet."
            ),
        )

    mean = sum(months) // n
    # Residuals: deviation of each month from the mean (negative = a low month).
    residuals = [m - mean for m in months]

    rng = random.Random(seed)
    # Bootstrap a month's residual ``num_samples`` times; collect the SHORTFALLS
    # (how far below the mean a sampled month lands). A non-negative residual is no
    # shortfall (0). Consume rng in a fixed order → deterministic.
    shortfalls: list[int] = []
    for _ in range(num_samples):
        resid = rng.choice(residuals)
        shortfalls.append(max(0, -resid))
    shortfalls.sort()

    # The buffer covers the (1 - target_percentile) upper tail of shortfalls — a
    # 20th-percentile LOW month is an 80th-percentile shortfall. So sample at
    # ``1 - target_percentile``.
    buffer_cents = _percentile_sorted(shortfalls, 1.0 - target_percentile)

    return SmoothingRecommendation(
        recommended_buffer_cents=int(buffer_cents),
        months_observed=n,
        mean_monthly_cents=mean,
        target_percentile=target_percentile,
        sufficient_data=True,
        rationale=(
            f"Over {n} months your self-employment income averaged "
            f"{mean} cents/month. Holding back {int(buffer_cents)} cents smooths a "
            f"low month at the {int(target_percentile * 100)}th percentile."
        ),
    )


def recommend_for_user(
    db: Session,
    user_id: int,
    *,
    window_months: int = DEFAULT_WINDOW_MONTHS,
    target_percentile: float = DEFAULT_TARGET_PERCENTILE,
    seed: int = DEFAULT_SEED,
    num_samples: int = DEFAULT_NUM_SAMPLES,
) -> SmoothingRecommendation:
    """End-to-end recommendation for a user: pull their monthly SE income, recommend.

    Does NOT write ``User.s2s_buffer`` — applying the recommendation is the separate
    one-tap accept step (guardrail B2). Deterministic under ``seed``.
    """
    by_month = monthly_self_employment_income_cents(
        db, user_id, window_months=window_months
    )
    return recommend_buffer(
        list(by_month.values()),
        target_percentile=target_percentile,
        seed=seed,
        num_samples=num_samples,
    )


def apply_recommendation(
    db: Session, user_id: int, recommendation: SmoothingRecommendation
) -> Optional[int]:
    """Apply a recommendation by writing ``User.s2s_buffer`` (the one-tap accept).

    Returns the new buffer (cents) on success, or None if the user is missing.
    This is the ONLY function here that writes; it is invoked explicitly on accept,
    never automatically (B2). Caller commits.
    """
    from server.src.db.models import User as UserORM

    user = db.get(UserORM, user_id)
    if user is None:
        return None
    user.s2s_buffer = int(recommendation.recommended_buffer_cents)
    db.flush()
    return user.s2s_buffer
