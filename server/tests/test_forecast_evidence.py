from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import random

from sqlalchemy import select

from server.src.db.models import (
    Account,
    ForecastDailyObservation,
    ForecastEvidenceOrigin,
    User,
)
from server.src.services.forecast_evidence_service import (
    ForecastEvidenceService,
    MODEL_VERSION,
)
from server.src.services.forecast_service import ForecastService
from server.src.services.transaction_service import TransactionService
from server.src.settings import settings


NOW = datetime(2026, 7, 23, 2, 10, tzinfo=timezone.utc)


def _owner(db, uid: int = 1) -> User:
    user = User(
        id=uid,
        username=f"evidence-{uid}",
        full_name="Evidence Owner",
        email=f"evidence-{uid}@example.test",
        hashed_password="unused",
    )
    db.add(user)
    db.flush()
    return user


def _account(
    db,
    user_id: int,
    *,
    type_: str = "checking",
    plaid_id: str | None = "plaid-checking",
    updated: datetime | None = NOW,
    plaid_refreshed: datetime | None = NOW,
    balance: int = 50_000,
) -> Account:
    row = Account(
        name=f"Account-{user_id}-{type_}",
        type=type_,
        balance=balance,
        plaid_account_id=plaid_id,
        last_updated=updated,
        plaid_balance_refreshed_at=plaid_refreshed,
        user_id=user_id,
    )
    db.add(row)
    db.flush()
    return row


def test_manual_stale_or_credit_accounts_never_make_valid_origin(db_session):
    user = _owner(db_session)
    _account(
        db_session,
        user.id,
        type_="credit",
        plaid_id=None,
        updated=NOW - timedelta(days=4),
        plaid_refreshed=NOW - timedelta(days=4),
    )
    service = ForecastEvidenceService(db_session)
    obs = service.capture_observation(user.id, observed_at=NOW)
    assert not obs.eligible
    assert "manual_or_unlinked_account" in (obs.invalid_reason or "")
    assert "unsupported_account_type:credit" in (obs.invalid_reason or "")
    assert "stale_or_unknown_balance" in (obs.invalid_reason or "")

    assert service.capture_origins(user.id, obs) == 3
    origins = db_session.execute(select(ForecastEvidenceOrigin)).scalars().all()
    assert {row.status for row in origins} == {"invalid"}
    assert all(row.realized_trough_cents is None for row in origins)


def test_local_touch_cannot_make_a_stale_plaid_balance_fresh(db_session):
    user = _owner(db_session)
    account = _account(
        db_session,
        user.id,
        updated=NOW,
        plaid_refreshed=NOW,
    )
    TransactionService(db_session)._adjust_balance(account.id, -100)
    db_session.expire(account)
    assert account.plaid_balance_refreshed_at is None
    obs = ForecastEvidenceService(db_session).capture_observation(
        user.id, observed_at=NOW
    )
    assert not obs.eligible
    assert obs.invalid_reason == "stale_or_unknown_balance"


def test_first_daily_observation_is_immutable_and_origins_are_idempotent(db_session):
    user = _owner(db_session)
    account = _account(db_session, user.id)
    service = ForecastEvidenceService(db_session)
    first = service.capture_observation(user.id, observed_at=NOW)
    account.balance = 1
    db_session.flush()
    second = service.capture_observation(user.id, observed_at=NOW + timedelta(hours=3))
    assert second.id == first.id
    assert second.total_cents == 50_000

    assert service.capture_origins(user.id, first) == 3
    assert service.capture_origins(user.id, first) == 0
    assert db_session.execute(select(ForecastEvidenceOrigin)).scalars().all().__len__() == 3


def test_valid_outcome_requires_every_day_and_the_exact_account_set(db_session):
    user = _owner(db_session)
    _account(db_session, user.id)
    service = ForecastEvidenceService(db_session)
    origin_obs = service.capture_observation(user.id, observed_at=NOW)
    service.capture_origins(user.id, origin_obs)
    origin = db_session.execute(
        select(ForecastEvidenceOrigin).where(ForecastEvidenceOrigin.horizon_days == 7)
    ).scalar_one()

    for offset in range(1, 8):
        db_session.add(
            ForecastDailyObservation(
                user_id=user.id,
                observed_date=(NOW.date() + timedelta(days=offset)).isoformat(),
                observed_at=NOW + timedelta(days=offset),
                total_cents=50_000 - offset * 1_000,
                account_set_hash=origin.account_set_hash,
                account_count=1,
                source_type_counts_json='{"sources":{"plaid":1},"types":{"checking":1}}',
                freshness_json="{}",
                eligible=1,
            )
        )
    db_session.flush()
    assert service.mature_due(user.id, as_of=NOW.date() + timedelta(days=7)) == 1
    assert origin.status == "valid"
    assert origin.observed_days == 8
    assert origin.realized_trough_cents == 43_000


def test_gap_or_account_set_change_invalidates_instead_of_synthesizing(db_session):
    user = _owner(db_session)
    _account(db_session, user.id)
    service = ForecastEvidenceService(db_session)
    obs = service.capture_observation(user.id, observed_at=NOW)
    service.capture_origins(user.id, obs)
    origin = db_session.execute(
        select(ForecastEvidenceOrigin).where(ForecastEvidenceOrigin.horizon_days == 7)
    ).scalar_one()
    # Deliberately omit day 3. The job must leave the gap visible.
    for offset in (1, 2, 4, 5, 6, 7):
        db_session.add(
            ForecastDailyObservation(
                user_id=user.id,
                observed_date=(NOW.date() + timedelta(days=offset)).isoformat(),
                observed_at=NOW + timedelta(days=offset),
                total_cents=49_000,
                account_set_hash="changed" if offset == 4 else origin.account_set_hash,
                account_count=1,
                source_type_counts_json="{}",
                freshness_json="{}",
                eligible=1,
            )
        )
    db_session.flush()
    service.mature_due(user.id, as_of=NOW.date() + timedelta(days=7))
    assert origin.status == "invalid"
    assert origin.reason == "missing_daily_observation"
    assert origin.realized_trough_cents is None


def test_summary_is_owner_scoped_and_labels_overlap_caveat(db_session):
    owner_a = _owner(db_session, 1)
    owner_b = _owner(db_session, 2)
    _account(db_session, owner_a.id)
    _account(db_session, owner_b.id, balance=90_000)
    service = ForecastEvidenceService(db_session)
    for owner in (owner_a, owner_b):
        obs = service.capture_observation(owner.id, observed_at=NOW)
        service.capture_origins(owner.id, obs)
    summary = service.summary(owner_a.id)
    assert summary["descriptive_only"] is True
    assert summary["capture"]["observed_days"] == 1
    assert all(sum(h["counts"].values()) == 1 for h in summary["horizons"])
    assert any("Overlapping origins" in caveat for caveat in summary["caveats"])
    assert all("brier_score" not in horizon for horizon in summary["horizons"])


def test_evidence_capture_does_not_change_seeded_production_forecast(db_session):
    user = _owner(db_session)
    _account(db_session, user.id)
    before = ForecastService(db_session).forecast(
        user.id,
        NOW.date(),
        NOW.date() + timedelta(days=30),
        include_burn=True,
        rng=random.Random(91),
    )
    ForecastEvidenceService(db_session).capture_and_mature_user(user.id, now=NOW)
    after = ForecastService(db_session).forecast(
        user.id,
        NOW.date(),
        NOW.date() + timedelta(days=30),
        include_burn=True,
        rng=random.Random(91),
    )
    assert before == after
    assert db_session.execute(
        select(ForecastEvidenceOrigin.model_version).distinct()
    ).scalars().all() == [MODEL_VERSION]


def test_input_fingerprint_changes_with_actual_numeric_inputs(db_session):
    user = _owner(db_session)
    account = _account(db_session, user.id)
    service = ForecastEvidenceService(db_session)
    observation = service.capture_observation(user.id, observed_at=NOW)
    first = service._forecast_input_hash(user.id, NOW.date(), 7, observation)
    observation.total_cents += 1
    account.balance += 1
    second = service._forecast_input_hash(user.id, NOW.date(), 7, observation)
    assert first != second


def test_confidence_interval_is_reserved_for_disjoint_origins():
    row = ForecastEvidenceOrigin(
        user_id=1,
        origin_date="2026-07-01",
        end_date="2026-07-08",
        horizon_days=7,
        model_version=MODEL_VERSION,
        input_hash="x",
        account_set_hash="a",
        predicted_low_cents=0,
        predicted_median_cents=50,
        predicted_high_cents=100,
        overdraft_probability=0.0,
        nominal_coverage=0.9,
        expected_days=8,
        observed_days=8,
        realized_trough_cents=50,
        status="valid",
    )
    assert ForecastEvidenceService._stats(
        [row], inferential=False
    )["coverage_95pct_interval"] is None
    assert ForecastEvidenceService._stats(
        [row], inferential=True
    )["coverage_95pct_interval"] is not None


def test_default_flag_is_off_and_migration_has_explicit_rls():
    from pathlib import Path

    from server.src.settings import Settings

    assert Settings.model_fields["forecast_evidence_enabled"].default is False
    migration = Path(
        "server/migrations/versions/e5b220260723_forecast_evidence_pilot.py"
    ).read_text()
    for table in ("forecast_daily_observations", "forecast_evidence_origins"):
        assert table in migration
        assert "enable_rls(bind, table)" in migration
        assert "DROP POLICY IF EXISTS {table}_tenant_isolation" in migration


def test_evidence_route_ships_dark_and_is_owner_summary(client, monkeypatch):
    response = client.post(
        "/api/signup/",
        json={
            "username": "evidence-api",
            "email": "evidence-api@example.com",
            "full_name": "Evidence API",
            "password": "Test-password1",
        },
    )
    token = response.json()["access_token"]
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(settings, "forecast_evidence_enabled", False)
    assert client.get("/api/forecast/evidence/", headers=headers).status_code == 404
    monkeypatch.setattr(settings, "forecast_evidence_enabled", True)
    enabled = client.get("/api/forecast/evidence/", headers=headers)
    assert enabled.status_code == 200
    assert enabled.json()["descriptive_only"] is True
    assert enabled.json()["capture"]["observed_days"] == 0
