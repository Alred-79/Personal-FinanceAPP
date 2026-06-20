"""W5 — the income-volatility router seam (GET /spend/income-volatility/).

Covers the feature-flag gate (404 when off), the W-2 vs self-employment monthly
split, a positive deterministic buffer for a lumpy series, a ~0 buffer for flat
income, and that money crosses the boundary as dollars (not cents).
"""

from __future__ import annotations

import pytest

from server.src.db.models import Account as AccountORM, Income as IncomeORM


@pytest.fixture(autouse=True)
def _freelancer_on(monkeypatch):
    from server.src.settings import settings

    monkeypatch.setattr(settings, "freelancer_mode_enabled", True, raising=False)
    yield


def _auth(client, username="freeluser", email="freel@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Freelancer",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _account(client, headers):
    client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": 1000.0},
        headers=headers,
    )
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


def _seed_income(db, acct_id, cents, ym, source_type):
    uid = db.get(AccountORM, acct_id).user_id
    db.add(
        IncomeORM(
            title="Gig" if source_type == "self_employment" else "Salary",
            amount=cents,
            date=f"{ym}-15",
            category="Work",
            account_id=acct_id,
            user_id=uid,
            source_type=source_type,
        )
    )


def test_flag_off_returns_404(client, monkeypatch):
    from server.src.settings import settings

    monkeypatch.setattr(settings, "freelancer_mode_enabled", False, raising=False)
    headers = _auth(client)
    resp = client.get("/api/spend/income-volatility/", headers=headers)
    assert resp.status_code == 404


def test_split_and_positive_buffer(client, db_session):
    headers = _auth(client)
    acct = _account(client, headers)

    # A lumpy self-employment series ($9k / $1k alternating) + one W-2 paycheck.
    lumpy = [
        (900000, "2026-01"),
        (100000, "2026-02"),
        (800000, "2026-03"),
        (200000, "2026-04"),
        (700000, "2026-05"),
        (300000, "2026-06"),
    ]
    for cents, ym in lumpy:
        _seed_income(db_session, acct, cents, ym, "self_employment")
    _seed_income(db_session, acct, 500000, "2026-03", "w2")  # $5k salary in March
    db_session.commit()

    resp = client.get("/api/spend/income-volatility/", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["sufficient_data"] is True
    assert data["months_observed"] == 6
    assert data["recommended_buffer"] > 0  # lumpy → a real buffer
    assert data["mean_monthly"] == 5000.0  # dollars, not 500000 cents
    assert data["coefficient_of_variation"] is not None

    # March carries both an SE gig and a W-2 paycheck — the split must separate them.
    march = next(m for m in data["months"] if m["month"] == "2026-03")
    assert march["self_employment"] == 8000.0
    assert march["w2"] == 5000.0
    assert march["total"] == 13000.0


def test_flat_income_zero_buffer(client, db_session):
    headers = _auth(client, username="flatuser", email="flat@example.com")
    acct = _account(client, headers)
    for ym in ["2026-01", "2026-02", "2026-03", "2026-04"]:
        _seed_income(db_session, acct, 500000, ym, "self_employment")
    db_session.commit()

    data = client.get("/api/spend/income-volatility/", headers=headers).json()
    assert data["sufficient_data"] is True
    assert data["recommended_buffer"] == 0.0  # no dispersion → no buffer
