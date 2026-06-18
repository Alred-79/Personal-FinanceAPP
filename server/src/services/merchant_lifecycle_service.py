"""F2 — the Merchant Lifecycle Engine (pooled BG/NBD).

Competitors' subscription detection is calendar-pattern-bound and breaks on
irregular cadences (28–32-day gym billing, annual renewals). This models each
payee's *buying process* instead: a **BG/NBD** model (Fader–Hardie–Lee 2005),
**pooled across the user's payees-as-population** — the single-user reframe that
makes the statistics work (one merchant has too little data; the user's many
merchants are the population the priors pool over). Per merchant it yields:

* ``probability_alive`` — the zombie / lapsed-subscription detector (a merchant
  that billed regularly and then went silent past its cadence drops toward 0).
* ``expected_purchases`` over a horizon — the drop-adjusted forward rate.

Paired with a **deterministic price-creep** comparison (last charge vs the prior
stable amount) — that comparison is pure arithmetic and never touches the model.

The fit is a batch job (seconds), so its outputs are **snapshotted** into
``MerchantLifecycle`` and refreshed by F3's nightly job; reads never fit inline.
Gated behind ``settings.merchant_lifecycle_enabled`` and the single-worker
scheduler invariant.

Law: the model does the math; any narration of these numbers (the Clerk, the
Auditor) only phrases what the snapshot already computed.

PyMC / SciPy are imported lazily so this module loads even where they're absent
(the feature is flag-gated). The BG/NBD likelihood is implemented directly in
**core PyMC** — the ``pymc-marketing`` ``BetaGeoModel`` wrapper is incompatible
with the installed pytensor on Python 3.13, while core ``pymc`` + ``find_MAP``
work; the math is identical.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    MerchantLifecycle as MerchantLifecycleORM,
)
from ..settings import settings
from .categorization_service import normalize_merchant
from .recurring_service import next_occurrence
from .subscription_service import _classify_cadence

logger = logging.getLogger(__name__)

# Time unit for the model: weeks (keeps T/α numerically tame vs days).
_DAYS_PER_UNIT = 7.0

# A merchant needs at least this many charges to enter the fit / be snapshotted —
# below 2 there is no repeat behaviour to model.
_MIN_CHARGES = 2
# Need a population of at least this many repeat merchants before the pooled fit
# is trustworthy (a lone entity has too little data — the whole F2 reframe).
_MIN_MERCHANTS_FOR_FIT = 5

# probability_alive → status buckets (active / lapsing / dormant).
_STATUS_ACTIVE = 0.5
_STATUS_LAPSING = 0.15

# Price-creep: flag when the latest charge exceeds the prior stable amount by
# more than this fraction.
_PRICE_CREEP_THRESHOLD = 0.05


@dataclass(frozen=True)
class BGNBDParams:
    """Population-level BG/NBD parameters (Gamma(r, α) purchase rate; Beta(a, b)
    dropout). These ARE the hierarchical pooling — every merchant's
    ``probability_alive`` is read through them."""

    r: float
    alpha: float
    a: float
    b: float


@dataclass(frozen=True)
class MerchantSummary:
    """Per-merchant recency/frequency summary in model time units."""

    merchant: str
    title: str
    x: int  # repeat-transaction count (n_charges − 1)
    t_x: float  # recency: time of last charge from first (units)
    T: float  # observation span: first charge → as_of (units)
    n_charges: int
    last_date: str
    cadence: Optional[str]
    last_amount: int  # cents
    prev_amount: Optional[int]  # cents (median of prior charges)


# ── pure BG/NBD math (numpy/scipy; no DB) ───────────────────────────────────


def probability_alive(x: int, t_x: float, T: float, p: BGNBDParams) -> float:
    """P(customer still active at T | x, t_x, T) — the closed form (FHL eq 7).

    A merchant with no repeats (``x == 0``) has shown no death signal → 1.0. One
    that bought frequently (high x) but long ago (t_x ≪ T) drops toward 0."""
    if x <= 0:
        return 1.0
    try:
        factor = (p.a / (p.b + x - 1.0)) * (
            ((p.alpha + T) / (p.alpha + t_x)) ** (p.r + x)
        )
    except (OverflowError, ZeroDivisionError):
        return 0.0
    if math.isinf(factor):
        return 0.0
    return 1.0 / (1.0 + factor)


def expected_purchases(
    x: int, t_x: float, T: float, t_future: float, p: BGNBDParams
) -> float:
    """Conditional expected transactions in the next ``t_future`` units.

    Uses the exact BG/NBD expectation (FHL eq 10, via the Gaussian hypergeometric
    ₂F₁) when it is well-defined (``a > 1``); otherwise falls back to the
    drop-adjusted posterior rate ``P(alive) · (r+x)/(α+T) · t`` — the same
    quantity to first order, finite for any fit."""
    if t_future <= 0:
        return 0.0
    pa = probability_alive(x, t_x, T, p)
    if p.a > 1.0:
        try:
            from scipy.special import hyp2f1  # lazy

            z = t_future / (p.alpha + T + t_future)
            hyp = float(hyp2f1(p.r + x, p.b + x, p.a + p.b + x - 1.0, z))
            term1 = (p.a + p.b + x - 1.0) / (p.a - 1.0)
            term2 = 1.0 - ((p.alpha + T) / (p.alpha + T + t_future)) ** (p.r + x) * hyp
            denom = 1.0
            if x > 0:
                denom = 1.0 + (p.a / (p.b + x - 1.0)) * (
                    ((p.alpha + T) / (p.alpha + t_x)) ** (p.r + x)
                )
            val = (term1 * term2) / denom
            if math.isfinite(val) and val >= 0:
                return val
        except Exception:  # noqa: BLE001 — fall through to the rate approximation
            pass
    # Drop-adjusted posterior-rate fallback.
    rate = (p.r + x) / (p.alpha + T)
    return pa * rate * t_future


def fit_bgnbd(summaries: list[MerchantSummary], *, seed: int = 0) -> BGNBDParams:
    """MAP-fit the pooled BG/NBD parameters over the merchant population.

    Core PyMC + ``find_MAP`` (L-BFGS-B); deterministic from the model's fixed
    init, so a fixed input yields stable parameters. Raises ``RuntimeError`` if
    PyMC is unavailable (the caller only fits when the feature is enabled)."""
    try:
        import numpy as np
        import pymc as pm
        import pytensor.tensor as pt
    except ImportError as exc:  # pragma: no cover - exercised only without pymc
        raise RuntimeError("merchant lifecycle fit requires pymc") from exc

    x = np.array([s.x for s in summaries], dtype=float)
    t_x = np.array([s.t_x for s in summaries], dtype=float)
    T = np.array([s.T for s in summaries], dtype=float)

    with pm.Model():
        # Gamma (shape 2) priors, not HalfNormal: their density vanishes at 0, so
        # the MAP can't collapse the dropout params to a≈0 ("nobody ever churns")
        # when the population is dominated by still-active merchants — the known
        # BG/NBD MAP pathology. Means: r≈2, α≈10, a≈2, b≈2.
        r = pm.Gamma("r", alpha=2.0, beta=1.0)
        alpha = pm.Gamma("alpha", alpha=2.0, beta=0.2)
        a = pm.Gamma("a", alpha=2.0, beta=1.0)
        b = pm.Gamma("b", alpha=2.0, beta=1.0)
        # FHL (2005) individual log-likelihood, summed over the population.
        ln_a1 = pt.gammaln(r + x) - pt.gammaln(r) + r * pt.log(alpha)
        ln_a2 = (
            pt.gammaln(a + b)
            + pt.gammaln(b + x)
            - pt.gammaln(b)
            - pt.gammaln(a + b + x)
        )
        a3 = (alpha + T) ** (-(r + x))
        delta = pt.gt(x, 0)
        a4 = delta * (a / (b + x - 1.0)) * (alpha + t_x) ** (-(r + x))
        pm.Potential("ll", pt.sum(ln_a1 + ln_a2 + pt.log(a3 + a4)))
        mp = pm.find_MAP(method="L-BFGS-B", progressbar=False, seed=seed)

    return BGNBDParams(
        r=float(mp["r"]), alpha=float(mp["alpha"]),
        a=float(mp["a"]), b=float(mp["b"]),
    )


def status_for(probability: float) -> str:
    if probability >= _STATUS_ACTIVE:
        return "active"
    if probability >= _STATUS_LAPSING:
        return "lapsing"
    return "dormant"


def price_creep_pct(last_amount: int, prev_amount: Optional[int]) -> Optional[float]:
    """Fractional increase of the latest charge over the prior stable amount, or
    None when there's no prior or it isn't a meaningful rise."""
    if not prev_amount or prev_amount <= 0:
        return None
    pct = (last_amount - prev_amount) / prev_amount
    return pct if pct > _PRICE_CREEP_THRESHOLD else None


# ── the service (DB I/O + snapshot) ─────────────────────────────────────────


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _median_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


class MerchantLifecycleService:
    """Builds merchant summaries, fits the pooled BG/NBD, and snapshots the
    per-merchant lifecycle into ``MerchantLifecycle``."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _summaries(
        self, user_id: int, as_of: date, lookback_days: int
    ) -> list[MerchantSummary]:
        cutoff = as_of - timedelta(days=lookback_days)
        rows = (
            self.db.execute(
                select(ExpenseORM)
                .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
                .where(AccountORM.user_id == user_id)
            )
            .scalars()
            .all()
        )
        groups: dict[str, list[tuple[date, int, str]]] = defaultdict(list)
        for r in rows:
            merchant = normalize_merchant(r.title or "")
            if not merchant:
                continue
            d = _parse_date(r.date)
            if d is None or d < cutoff or d > as_of:
                continue
            amt = int(r.amount or 0)
            if amt <= 0:
                continue
            groups[merchant].append((d, amt, r.title or ""))

        summaries: list[MerchantSummary] = []
        for merchant, charges in groups.items():
            if len(charges) < _MIN_CHARGES:
                continue
            charges.sort(key=lambda c: c[0])
            dates = [c[0] for c in charges]
            amounts = [c[1] for c in charges]
            first, last = dates[0], dates[-1]
            T = max((as_of - first).days, 0) / _DAYS_PER_UNIT
            t_x = max((last - first).days, 0) / _DAYS_PER_UNIT
            intervals = [
                (dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)
            ]
            summaries.append(
                MerchantSummary(
                    merchant=merchant,
                    title=charges[-1][2],
                    x=len(charges) - 1,
                    t_x=t_x,
                    T=T,
                    n_charges=len(charges),
                    last_date=last.isoformat(),
                    cadence=_classify_cadence(intervals),
                    last_amount=amounts[-1],
                    prev_amount=_median_int(amounts[:-1]) or None,
                )
            )
        return summaries

    def refresh(
        self, user_id: int, as_of: Optional[date] = None
    ) -> list[dict[str, Any]]:
        """Re-fit and re-snapshot the user's merchant lifecycles. Idempotent
        (upserts one row per (user, merchant)); returns the snapshot dicts.

        No-op (returns ``[]``) when the feature is off or the population is too
        small to fit. Pure read of the model inputs; the only writes are the
        snapshot rows."""
        as_of = as_of or date.today()
        if not settings.merchant_lifecycle_enabled:
            return []
        summaries = self._summaries(
            user_id, as_of, settings.merchant_lifecycle_lookback_days
        )
        if len(summaries) < _MIN_MERCHANTS_FOR_FIT:
            return []

        try:
            params = fit_bgnbd(summaries, seed=0)
        except Exception:  # noqa: BLE001 — a fit failure must not crash the job
            logger.exception("merchant lifecycle fit failed: user=%s", user_id)
            return []

        horizon = settings.merchant_lifecycle_horizon_days / _DAYS_PER_UNIT
        fitted_at = datetime.now(timezone.utc).isoformat()
        snapshots: list[dict[str, Any]] = []
        for s in summaries:
            pa = probability_alive(s.x, s.t_x, s.T, params)
            ep = expected_purchases(s.x, s.t_x, s.T, horizon, params)
            pct = price_creep_pct(s.last_amount, s.prev_amount)
            nxt = None
            if s.cadence:
                d = _parse_date(s.last_date)
                occ = next_occurrence(d, s.cadence) if d else None
                nxt = occ.isoformat() if occ else None
            snap = {
                "merchant": s.merchant,
                "title": s.title,
                "probability_alive": round(pa, 4),
                "expected_purchases": round(ep, 4),
                "status": status_for(pa),
                "cadence": s.cadence,
                "n_charges": s.n_charges,
                "last_amount": s.last_amount,
                "prev_amount": s.prev_amount,
                "price_change_pct": round(pct, 4) if pct is not None else None,
                "last_date": s.last_date,
                "expected_next_date": nxt,
                "fitted_at": fitted_at,
            }
            self._upsert(user_id, snap)
            snapshots.append(snap)
        self.db.flush()
        return snapshots

    def _upsert(self, user_id: int, snap: dict[str, Any]) -> None:
        row = self.db.execute(
            select(MerchantLifecycleORM).where(
                MerchantLifecycleORM.user_id == user_id,
                MerchantLifecycleORM.merchant == snap["merchant"],
            )
        ).scalar_one_or_none()
        if row is None:
            row = MerchantLifecycleORM(user_id=user_id, merchant=snap["merchant"])
            self.db.add(row)
        row.title = snap["title"]
        row.probability_alive = snap["probability_alive"]
        row.expected_purchases = snap["expected_purchases"]
        row.status = snap["status"]
        row.cadence = snap["cadence"]
        row.n_charges = snap["n_charges"]
        row.last_amount = snap["last_amount"]
        row.prev_amount = snap["prev_amount"]
        row.price_change_pct = snap["price_change_pct"]
        row.last_date = snap["last_date"]
        row.expected_next_date = snap["expected_next_date"]
        row.fitted_at = snap["fitted_at"]

    def list_snapshots(self, user_id: int) -> list[dict[str, Any]]:
        """Read the snapshotted lifecycles (no fit). Dollar conversion is left to
        the router boundary."""
        rows = (
            self.db.execute(
                select(MerchantLifecycleORM)
                .where(MerchantLifecycleORM.user_id == user_id)
                .order_by(MerchantLifecycleORM.probability_alive.asc())
            )
            .scalars()
            .all()
        )
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(r: MerchantLifecycleORM) -> dict[str, Any]:
        return {
            "merchant": r.merchant,
            "title": r.title,
            "probability_alive": r.probability_alive,
            "expected_purchases": r.expected_purchases,
            "status": r.status,
            "cadence": r.cadence,
            "n_charges": r.n_charges,
            "last_amount": r.last_amount,
            "prev_amount": r.prev_amount,
            "price_change_pct": r.price_change_pct,
            "last_date": r.last_date,
            "expected_next_date": r.expected_next_date,
            "fitted_at": r.fitted_at,
        }
