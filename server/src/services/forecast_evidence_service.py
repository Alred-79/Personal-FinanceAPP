"""Dark, descriptive evidence capture for the unchanged production forecast.

This module does not calibrate or alter a forecast. It records one UTC balance
observation, then captures same-day forecasts only when the *entire* production
account set has known positive-cash semantics, is Plaid-linked, and is fresh.
Future outcomes are matured exclusively from stored daily observations.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account,
    ForecastDailyObservation,
    ForecastEvidenceOrigin,
)
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.services.forecast_service import ForecastService, _BURN_WINDOW_DAYS
from server.src.services.recurring_service import RecurringService
from server.src.settings import settings


HORIZONS = (7, 14, 30)
MODEL_VERSION = "forecast-service:block-bootstrap:v1"
# These are the only local Account.type values for which this pilot asserts that
# a positive balance means liquid cash. Unknown/subtle Plaid subtypes fail closed.
LIQUID_POSITIVE_TYPES = frozenset(
    {"checking", "savings", "depository", "cash", "money market"}
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _stable_seed(user_id: int, origin: date, horizon: int) -> int:
    digest = hashlib.sha256(
        f"{user_id}:{origin.isoformat()}:{horizon}:{MODEL_VERSION}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _is_disjoint(origin: date, horizon: int) -> bool:
    # A realized trough includes both origin and end observations, so spacing by
    # horizon+1 (not horizon) makes the predeclared stream truly non-overlapping.
    return (origin - date(1970, 1, 1)).days % (horizon + 1) == 0


class ForecastEvidenceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _account_snapshot(self, user_id: int, now: datetime) -> dict[str, Any]:
        accounts = self.db.execute(
            select(Account).where(Account.user_id == user_id).order_by(Account.id)
        ).scalars().all()
        account_identity = [
            {
                "id": row.id,
                "plaid_account_id": row.plaid_account_id,
                "type": (row.type or "").strip().lower(),
            }
            for row in accounts
        ]
        account_hash = _sha(account_identity)
        type_counts = Counter(item["type"] or "unknown" for item in account_identity)
        reasons: list[str] = []
        if not accounts:
            reasons.append("no_accounts")
        if any(not row.plaid_account_id for row in accounts):
            reasons.append("manual_or_unlinked_account")
        unsupported = sorted(
            {item["type"] or "unknown" for item in account_identity}
            - LIQUID_POSITIVE_TYPES
        )
        if unsupported:
            reasons.append("unsupported_account_type:" + ",".join(unsupported))

        age_limit = timedelta(hours=max(1, settings.forecast_evidence_max_age_hours))
        ages: list[float] = []
        stale = False
        for row in accounts:
            if row.plaid_balance_refreshed_at is None:
                stale = True
                continue
            updated = _utc(row.plaid_balance_refreshed_at)
            age = now - updated
            ages.append(max(0.0, age.total_seconds() / 3600))
            if age < timedelta(0) or age > age_limit:
                stale = True
        if stale:
            reasons.append("stale_or_unknown_balance")

        return {
            "total_cents": sum(int(row.balance or 0) for row in accounts),
            "account_set_hash": account_hash,
            "account_count": len(accounts),
            "source_type_counts": {
                "sources": {"plaid": sum(bool(row.plaid_account_id) for row in accounts)},
                "types": dict(sorted(type_counts.items())),
            },
            "freshness": {
                "max_allowed_age_hours": settings.forecast_evidence_max_age_hours,
                "oldest_age_hours": round(max(ages), 3) if ages else None,
                "fresh_account_count": sum(
                    1
                    for row in accounts
                    if row.plaid_balance_refreshed_at is not None
                    and timedelta(0)
                    <= now - _utc(row.plaid_balance_refreshed_at)
                    <= age_limit
                ),
            },
            "eligible": not reasons,
            "invalid_reason": ";".join(reasons) if reasons else None,
        }

    def capture_observation(
        self, user_id: int, *, observed_at: datetime | None = None
    ) -> ForecastDailyObservation:
        now = _utc(observed_at or datetime.now(timezone.utc))
        observed_date = now.date().isoformat()
        existing = self.db.execute(
            select(ForecastDailyObservation).where(
                ForecastDailyObservation.user_id == user_id,
                ForecastDailyObservation.observed_date == observed_date,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing  # first observation is immutable

        snapshot = self._account_snapshot(user_id, now)
        row = ForecastDailyObservation(
            user_id=user_id,
            observed_date=observed_date,
            observed_at=now,
            total_cents=snapshot["total_cents"],
            account_set_hash=snapshot["account_set_hash"],
            account_count=snapshot["account_count"],
            source_type_counts_json=json.dumps(
                snapshot["source_type_counts"], sort_keys=True, separators=(",", ":")
            ),
            freshness_json=json.dumps(
                snapshot["freshness"], sort_keys=True, separators=(",", ":")
            ),
            eligible=int(snapshot["eligible"]),
            invalid_reason=snapshot["invalid_reason"],
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _invalid_origin(
        self, user_id: int, origin: date, horizon: int, observation: ForecastDailyObservation
    ) -> ForecastEvidenceOrigin:
        return ForecastEvidenceOrigin(
            user_id=user_id,
            origin_date=origin.isoformat(),
            end_date=(origin + timedelta(days=horizon)).isoformat(),
            horizon_days=horizon,
            model_version=MODEL_VERSION,
            input_hash=_sha({"account_set_hash": observation.account_set_hash, "horizon": horizon}),
            account_set_hash=observation.account_set_hash,
            predicted_low_cents=0,
            predicted_median_cents=0,
            predicted_high_cents=0,
            overdraft_probability=0.0,
            nominal_coverage=settings.forecast_coverage_level or None,
            heuristic_widening_ran=0,
            expected_days=horizon + 1,
            observed_days=1,
            status="invalid",
            reason=observation.invalid_reason or "ineligible_origin_observation",
            disjoint_stream=int(_is_disjoint(origin, horizon)),
            matured_at=observation.observed_at,
        )

    def _forecast_input_hash(
        self,
        user_id: int,
        origin: date,
        horizon: int,
        observation: ForecastDailyObservation,
    ) -> str:
        """Fingerprint the actual numeric inputs that produce an evidence band.

        Raw merchant labels never enter the fingerprint. Repeated projected
        flows remain repeated in the canonical list, while the burn residual
        pool and regime decision capture the historical stochastic inputs.
        """
        forecast_service = ForecastService(self.db)
        burn_window, regime_shift = forecast_service._regime_router(
            user_id, origin, _BURN_WINDOW_DAYS
        )
        burn_cents = forecast_service._discretionary_burn_cents(
            user_id, origin, window_days=burn_window
        )
        residual_pool = forecast_service._burn_residual_pool_cents(
            user_id, origin, burn_cents, window_days=burn_window
        )
        projected = RecurringService(self.db).project_cashflows(
            user_id, origin, origin + timedelta(days=horizon)
        )
        flows = sorted(
            (
                str(item["date"]),
                str(item["type"]),
                dollars_to_cents(item["amount"]),
            )
            for item in projected
        )
        return _sha(
            {
                "model_version": MODEL_VERSION,
                "origin": origin.isoformat(),
                "horizon": horizon,
                "starting_balance_cents": observation.total_cents,
                "account_set_hash": observation.account_set_hash,
                "scheduled_flows": flows,
                "burn_window_days": burn_window,
                "daily_burn_cents": burn_cents,
                "residual_pool_cents": residual_pool,
                "regime_shift": regime_shift,
                "sim_block_days": settings.sim_block_days,
                "nominal_coverage": settings.forecast_coverage_level,
                "changepoint_enabled": settings.forecast_changepoint_enabled,
            }
        )

    def capture_origins(
        self, user_id: int, observation: ForecastDailyObservation
    ) -> int:
        origin = date.fromisoformat(observation.observed_date)
        created = 0
        for horizon in HORIZONS:
            exists = self.db.execute(
                select(ForecastEvidenceOrigin.id).where(
                    ForecastEvidenceOrigin.user_id == user_id,
                    ForecastEvidenceOrigin.origin_date == observation.observed_date,
                    ForecastEvidenceOrigin.horizon_days == horizon,
                    ForecastEvidenceOrigin.model_version == MODEL_VERSION,
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            if not observation.eligible:
                self.db.add(self._invalid_origin(user_id, origin, horizon, observation))
                created += 1
                continue

            input_hash = self._forecast_input_hash(
                user_id, origin, horizon, observation
            )
            forecast = ForecastService(self.db).forecast(
                user_id,
                origin,
                origin + timedelta(days=horizon),
                include_burn=True,
                rng=random.Random(_stable_seed(user_id, origin, horizon)),
            )
            band = forecast["trough_band"]
            self.db.add(
                ForecastEvidenceOrigin(
                    user_id=user_id,
                    origin_date=origin.isoformat(),
                    end_date=(origin + timedelta(days=horizon)).isoformat(),
                    horizon_days=horizon,
                    model_version=MODEL_VERSION,
                    input_hash=input_hash,
                    account_set_hash=observation.account_set_hash,
                    predicted_low_cents=dollars_to_cents(band["low"]),
                    predicted_median_cents=dollars_to_cents(band["median"]),
                    predicted_high_cents=dollars_to_cents(band["high"]),
                    overdraft_probability=float(forecast["overdraft_probability"]),
                    nominal_coverage=forecast.get("coverage_level"),
                    heuristic_widening_ran=int(bool(forecast.get("band_calibrated"))),
                    expected_days=horizon + 1,
                    observed_days=1,
                    status="pending",
                    disjoint_stream=int(_is_disjoint(origin, horizon)),
                )
            )
            created += 1
        self.db.flush()
        return created

    def mature_due(self, user_id: int, *, as_of: date) -> int:
        origins = self.db.execute(
            select(ForecastEvidenceOrigin).where(
                ForecastEvidenceOrigin.user_id == user_id,
                ForecastEvidenceOrigin.status == "pending",
                ForecastEvidenceOrigin.end_date <= as_of.isoformat(),
            )
        ).scalars().all()
        matured = 0
        now = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
        for origin in origins:
            start = date.fromisoformat(origin.origin_date)
            end = date.fromisoformat(origin.end_date)
            expected_dates = [
                (start + timedelta(days=i)).isoformat()
                for i in range((end - start).days + 1)
            ]
            observations = self.db.execute(
                select(ForecastDailyObservation)
                .where(
                    ForecastDailyObservation.user_id == user_id,
                    ForecastDailyObservation.observed_date >= origin.origin_date,
                    ForecastDailyObservation.observed_date <= origin.end_date,
                )
                .order_by(ForecastDailyObservation.observed_date)
            ).scalars().all()
            origin.observed_days = len(observations)
            by_date = {row.observed_date: row for row in observations}
            reason = None
            if set(by_date) != set(expected_dates):
                reason = "missing_daily_observation"
            elif any(not row.eligible for row in observations):
                reason = "ineligible_daily_observation"
            elif any(row.account_set_hash != origin.account_set_hash for row in observations):
                reason = "account_set_changed"
            if reason is not None:
                origin.status = "invalid"
                origin.reason = reason
            else:
                origin.status = "valid"
                origin.realized_trough_cents = min(row.total_cents for row in observations)
            origin.matured_at = now
            matured += 1
        self.db.flush()
        return matured

    def capture_and_mature_user(
        self, user_id: int, *, now: datetime | None = None
    ) -> dict[str, int]:
        now = _utc(now or datetime.now(timezone.utc))
        observation = self.capture_observation(user_id, observed_at=now)
        origins = self.capture_origins(user_id, observation)
        matured = self.mature_due(user_id, as_of=now.date())
        return {"observations": 1, "origins": origins, "matured": matured}

    @staticmethod
    def _wilson(successes: int, n: int) -> list[float] | None:
        if n <= 0:
            return None
        z = 1.96
        p = successes / n
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        radius = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
        return [round(max(0.0, center - radius), 4), round(min(1.0, center + radius), 4)]

    @classmethod
    def _stats(
        cls, rows: list[ForecastEvidenceOrigin], *, inferential: bool = False
    ) -> dict[str, Any]:
        valid = [row for row in rows if row.status == "valid" and row.realized_trough_cents is not None]
        if not valid:
            return {
                "sample_count": 0,
                "observed_coverage": None,
                "coverage_95pct_interval": None,
                "mean_interval_width": None,
                "mean_winkler_score": None,
                "overdraft_event_count": 0,
                "overdraft_event_prevalence": None,
            }
        covered = sum(
            row.predicted_low_cents <= int(row.realized_trough_cents) <= row.predicted_high_cents
            for row in valid
        )
        widths = [row.predicted_high_cents - row.predicted_low_cents for row in valid]
        winklers: list[float] = []
        for row, width in zip(valid, widths):
            y = int(row.realized_trough_cents)
            coverage = row.nominal_coverage or 0.90
            alpha = max(0.001, 1.0 - coverage)
            penalty = 0.0
            if y < row.predicted_low_cents:
                penalty = 2 * (row.predicted_low_cents - y) / alpha
            elif y > row.predicted_high_cents:
                penalty = 2 * (y - row.predicted_high_cents) / alpha
            winklers.append(width + penalty)
        events = sum(int(row.realized_trough_cents) < 0 for row in valid)
        return {
            "sample_count": len(valid),
            "observed_coverage": round(covered / len(valid), 4),
            # Daily rolling origins overlap, so a binomial interval would be
            # invalid for that dependent sample. Only the predeclared disjoint
            # stream receives an inferential interval.
            "coverage_95pct_interval": (
                cls._wilson(covered, len(valid)) if inferential else None
            ),
            "mean_interval_width": cents_to_dollars(round(sum(widths) / len(widths))),
            "mean_winkler_score": cents_to_dollars(round(sum(winklers) / len(winklers))),
            "overdraft_event_count": events,
            "overdraft_event_prevalence": round(events / len(valid), 4),
        }

    def summary(self, user_id: int) -> dict[str, Any]:
        observations = self.db.execute(
            select(ForecastDailyObservation)
            .where(ForecastDailyObservation.user_id == user_id)
            .order_by(ForecastDailyObservation.observed_date)
        ).scalars().all()
        if observations:
            first = date.fromisoformat(observations[0].observed_date)
            last = date.fromisoformat(observations[-1].observed_date)
            # Measure through today's UTC operating date, not merely through the
            # last successful row. A scheduler outage therefore stays visible as
            # missing evidence even before the next capture eventually succeeds.
            expected_through = max(last, datetime.now(timezone.utc).date())
            scheduled_days = (expected_through - first).days + 1
        else:
            first = last = None
            scheduled_days = 0
        capture = {
            "first_date": first.isoformat() if first else None,
            "last_date": last.isoformat() if last else None,
            "observed_days": len(observations),
            "scheduled_days": scheduled_days,
            "completeness": round(len(observations) / scheduled_days, 4) if scheduled_days else None,
            "eligible_days": sum(bool(row.eligible) for row in observations),
        }

        rows = self.db.execute(
            select(ForecastEvidenceOrigin).where(ForecastEvidenceOrigin.user_id == user_id)
        ).scalars().all()
        horizons: list[dict[str, Any]] = []
        for horizon in HORIZONS:
            subset = [row for row in rows if row.horizon_days == horizon]
            statuses = Counter(row.status for row in subset)
            reasons = Counter(row.reason for row in subset if row.reason)
            disjoint = [row for row in subset if row.disjoint_stream]
            horizons.append(
                {
                    "horizon_days": horizon,
                    "counts": dict(sorted(statuses.items())),
                    "invalid_reasons": dict(sorted(reasons.items())),
                    "all_origins": self._stats(subset, inferential=False),
                    "predeclared_disjoint_origins": self._stats(
                        disjoint, inferential=True
                    ),
                }
            )
        return {
            "descriptive_only": True,
            "label": "Forecast evidence pilot — descriptive, not calibration",
            "capture": capture,
            "horizons": horizons,
            "caveats": [
                "Daily stored balances cannot observe an intraday trough.",
                "Overlapping origins are dependent; use the separately predeclared disjoint stream as the conservative view.",
                "The effective sample size of overlapping origins is lower than their row count and is not estimated automatically.",
                "Confidence intervals describe sampling uncertainty only and do not establish a deployment threshold.",
                "Event prevalence is descriptive; no probability-calibration or Brier claim is made.",
            ],
        }
