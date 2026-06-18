"""F2 — Merchant Lifecycle Engine (pooled BG/NBD) tests.

The model output is snapshot-validated, never fit in a request path. The fit is
deterministic from a fixed init, so ``probability_alive`` is stable within a
tolerance. Price-creep is a pure-function test (amount comparison).
"""

from __future__ import annotations

from datetime import date

import pytest

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    MerchantLifecycle as MerchantLifecycleORM,
    User as UserORM,
)
from server.src.services.merchant_lifecycle_service import (
    _MIN_MERCHANTS_FOR_FIT,
    BGNBDParams,
    MerchantLifecycleService,
    price_creep_pct,
    probability_alive,
    status_for,
)
from server.src.settings import settings


# ── pure-function unit tests (no DB, no pymc) ───────────────────────────────


def test_probability_alive_no_repeats_is_one():
    p = BGNBDParams(r=1.0, alpha=10.0, a=1.0, b=2.0)
    assert probability_alive(0, 0.0, 30.0, p) == 1.0


def test_probability_alive_drops_when_silent_past_cadence():
    """A merchant that bought often (high x) but long ago (t_x ≪ T) is less
    likely alive than one whose last buy is recent."""
    p = BGNBDParams(r=2.0, alpha=12.0, a=0.5, b=2.0)
    recent = probability_alive(10, 50.0, 52.0, p)  # last buy at wk 50 of 52
    silent = probability_alive(10, 20.0, 52.0, p)  # last buy at wk 20 of 52
    assert recent > silent
    assert silent < 0.5


def test_status_buckets():
    assert status_for(0.9) == "active"
    assert status_for(0.3) == "lapsing"
    assert status_for(0.05) == "dormant"


def test_price_creep_flags_increase_only():
    assert price_creep_pct(1599, 1199) == pytest.approx((1599 - 1199) / 1199, rel=1e-3)
    assert price_creep_pct(1199, 1199) is None  # flat
    assert price_creep_pct(1000, 1599) is None  # a decrease isn't creep
    assert price_creep_pct(1500, None) is None  # no prior


# ── integration: fit + snapshot on a planted population ─────────────────────


def _seed_user(db):
    user = UserORM(username="ml", full_name="ML U", email="ml@x.com",
                   hashed_password="x", savings_percent=0)
    db.add(user)
    db.flush()
    acct = AccountORM(name="Checking", type="checking", balance=500_00,
                      user_id=user.id)
    db.add(acct)
    db.flush()
    return user, acct


def _monthly_dates(n: int, start: tuple[int, int]) -> list[str]:
    y, m = start
    out: list[str] = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _add_charges(db, acct_id, title, dates, amount_cents):
    for d in dates:
        db.add(ExpenseORM(title=title, amount=amount_cents, date=d,
                          category="Subscriptions", account_id=acct_id))


@pytest.fixture
def planted(db_session, monkeypatch):
    """A population with healthy monthly subs, planted zombies, an annual, and a
    price-creep merchant."""
    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", True)
    user, acct = _seed_user(db_session)
    # 6 healthy monthly subscriptions, charging right up to the as_of date.
    for name in ("Spotify", "Netflix", "Hulu", "Cloudbox", "Newsdesk", "Audible"):
        _add_charges(db_session, acct.id, name, _monthly_dates(13, (2025, 6)), 15_00)
    # 2 zombies: monthly for 7 months, then silence (last charge 2025-12-01).
    for name in ("Oldbox", "Deadsub"):
        _add_charges(db_session, acct.id, name, _monthly_dates(7, (2025, 6)), 40_00)
    # an annual renewal (2 charges a year apart).
    _add_charges(db_session, acct.id, "Insurance", ["2024-06-15", "2025-06-15"], 300_00)
    # a price-creep merchant: flat then a jump on the latest charge.
    _add_charges(db_session, acct.id, "Streamer", _monthly_dates(5, (2026, 1)), 10_00)
    _add_charges(db_session, acct.id, "Streamer", ["2026-06-01"], 15_00)
    db_session.flush()
    return user


def test_refresh_flags_zombie_and_keeps_healthy_active(db_session, planted):
    as_of = date(2026, 6, 2)
    snaps = MerchantLifecycleService(db_session).refresh(planted.id, as_of=as_of)
    by_merchant = {s["merchant"]: s for s in snaps}

    # Healthy monthly payers are alive.
    for m in ("spotify", "netflix", "hulu"):
        assert by_merchant[m]["status"] == "active", by_merchant[m]
        assert by_merchant[m]["probability_alive"] >= 0.5

    # The planted zombies (silent ~6 months past a monthly cadence) are flagged.
    for m in ("oldbox", "deadsub"):
        assert by_merchant[m]["probability_alive"] < 0.5, by_merchant[m]
        assert by_merchant[m]["status"] in ("lapsing", "dormant")


def test_refresh_detects_price_creep(db_session, planted):
    snaps = MerchantLifecycleService(db_session).refresh(planted.id, as_of=date(2026, 6, 2))
    streamer = next(s for s in snaps if s["merchant"] == "streamer")
    assert streamer["last_amount"] == 15_00
    assert streamer["prev_amount"] == 10_00
    assert streamer["price_change_pct"] == pytest.approx(0.5, rel=1e-2)


def test_refresh_is_deterministic_and_idempotent(db_session, planted):
    svc = MerchantLifecycleService(db_session)
    first = {s["merchant"]: s["probability_alive"]
             for s in svc.refresh(planted.id, as_of=date(2026, 6, 2))}
    second = {s["merchant"]: s["probability_alive"]
              for s in svc.refresh(planted.id, as_of=date(2026, 6, 2))}
    for m, p in first.items():
        assert second[m] == pytest.approx(p, abs=1e-3)
    # Idempotent upsert: one row per (user, merchant), not duplicated on re-run.
    n_rows = db_session.query(MerchantLifecycleORM).filter(
        MerchantLifecycleORM.user_id == planted.id
    ).count()
    assert n_rows == len(first)


def test_disabled_flag_is_noop(db_session, planted, monkeypatch):
    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", False)
    assert MerchantLifecycleService(db_session).refresh(planted.id, as_of=date(2026, 6, 2)) == []


def test_cold_start_below_min_merchants_skips_gracefully(db_session, monkeypatch):
    """Cold start: a user with fewer than ``_MIN_MERCHANTS_FOR_FIT`` repeat
    merchants self-skips the pooled fit (the population is too small to be
    trustworthy). The refresh must run WITHOUT crashing, fit nothing (no pymc
    invoked), and write NO snapshot rows — the ship-dark guardrail for a sparse
    new user. The flag is ON, so this isolates the population-floor skip from the
    feature-flag skip covered above."""
    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", True)
    user, acct = _seed_user(db_session)

    # Only 3 repeat merchants (< the 5-merchant floor), each clearly fittable
    # on its own (monthly, charges right up to as_of) — so the ONLY reason to
    # skip is the population floor, not a per-merchant min-charge cutoff.
    assert _MIN_MERCHANTS_FOR_FIT == 5
    for name in ("Spotify", "Netflix", "Hulu"):
        _add_charges(db_session, acct.id, name, _monthly_dates(13, (2025, 6)), 15_00)
    db_session.flush()

    # Guard: if the fit were ever reached it would call pymc; assert it is NOT.
    import server.src.services.merchant_lifecycle_service as mls

    def _boom(*_a, **_k):
        raise AssertionError("fit_bgnbd must not run below the merchant floor")

    monkeypatch.setattr(mls, "fit_bgnbd", _boom)

    snaps = MerchantLifecycleService(db_session).refresh(user.id, as_of=date(2026, 6, 2))

    assert snaps == []  # nothing fitted, nothing returned
    n_rows = db_session.query(MerchantLifecycleORM).filter(
        MerchantLifecycleORM.user_id == user.id
    ).count()
    assert n_rows == 0  # no MerchantLifecycle rows written


def test_subscriptions_router_enriches_with_lifecycle(db_session, planted):
    """The /subscriptions read merges the lifecycle snapshot onto each detected
    subscription (status stamp + probability_alive) when the feature is on."""
    from server.src.models import UserInDB
    from server.src.routers.subscriptions import get_subscriptions

    MerchantLifecycleService(db_session).refresh(planted.id, as_of=date(2026, 6, 2))
    user = UserInDB(id=planted.id, username=planted.username, email=planted.email,
                    full_name=planted.full_name, disabled=False, hashed_password="x")
    subs = get_subscriptions(current_user=user, db=db_session)
    by_merchant = {s["merchant"]: s for s in subs}
    # A healthy monthly payer is detected AND carries its lifecycle stamp.
    assert "spotify" in by_merchant
    assert by_merchant["spotify"]["lifecycle_status"] == "active"
    assert "probability_alive" in by_merchant["spotify"]
