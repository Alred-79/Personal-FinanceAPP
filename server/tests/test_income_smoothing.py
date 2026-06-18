"""W5 — self-employment income smoothing (pure, seeded).

Covers: flat income → ~0 buffer; volatility → a positive, DETERMINISTIC buffer
under a fixed seed; only self_employment income contributes (W-2 / other / NULL
ignored); thin history self-skips with a 0 buffer; apply writes User.s2s_buffer.
"""

from __future__ import annotations

from server.src.db.models import (
    Account as AccountORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.services.income_smoothing import (
    DEFAULT_SEED,
    apply_recommendation,
    monthly_self_employment_income_cents,
    recommend_buffer,
    recommend_for_user,
)


def _user(db, username="freel"):
    u = UserORM(username=username, full_name="F", email=f"{username}@e.com",
                hashed_password="x")
    db.add(u)
    db.flush()
    return u


def _account(db, uid):
    a = AccountORM(name="Checking", type="depository", balance=0, user_id=uid)
    db.add(a)
    db.flush()
    return a


def _income(db, acct_id, title, cents, date, source_type=None):
    i = IncomeORM(title=title, amount=cents, date=date, category="Work",
                  account_id=acct_id, source_type=source_type)
    db.add(i)
    db.flush()
    return i


# ── pure recommend_buffer ────────────────────────────────────────────────────

class TestRecommendBuffer:
    def test_flat_income_zero_buffer(self):
        """A perfectly flat series has no dispersion → ~0 buffer."""
        rec = recommend_buffer([500000] * 12)
        assert rec.sufficient_data is True
        assert rec.recommended_buffer_cents == 0
        assert rec.mean_monthly_cents == 500000

    def test_volatility_positive_and_deterministic(self):
        """A lumpy series yields a positive buffer, identical across runs (seed)."""
        series = [900000, 100000, 800000, 200000, 700000, 300000,
                  900000, 100000, 850000, 150000, 800000, 200000]
        a = recommend_buffer(series)
        b = recommend_buffer(series)
        assert a.recommended_buffer_cents > 0
        # Byte-identical under the fixed default seed.
        assert a.recommended_buffer_cents == b.recommended_buffer_cents
        # A different seed is still deterministic per-seed.
        c = recommend_buffer(series, seed=DEFAULT_SEED + 1)
        d = recommend_buffer(series, seed=DEFAULT_SEED + 1)
        assert c.recommended_buffer_cents == d.recommended_buffer_cents

    def test_more_volatility_means_bigger_buffer(self):
        mild = [550000, 450000, 550000, 450000, 550000, 450000]
        wild = [1000000, 0, 1000000, 0, 1000000, 0]
        assert (
            recommend_buffer(wild).recommended_buffer_cents
            > recommend_buffer(mild).recommended_buffer_cents
        )

    def test_thin_history_self_skips(self):
        rec = recommend_buffer([500000, 400000])  # < _MIN_MONTHS
        assert rec.sufficient_data is False
        assert rec.recommended_buffer_cents == 0

    def test_empty_series(self):
        rec = recommend_buffer([])
        assert rec.sufficient_data is False
        assert rec.recommended_buffer_cents == 0


# ── DB integration: only self_employment contributes ─────────────────────────

class TestMonthlyAggregation:
    def test_only_self_employment_counts(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        # self_employment income across 3 distinct months
        _income(db, a.id, "Client A 1099", 800000, "2026-01-15", "self_employment")
        _income(db, a.id, "Client B 1099", 200000, "2026-02-15", "self_employment")
        _income(db, a.id, "Client C 1099", 600000, "2026-03-15", "self_employment")
        # noise that MUST be ignored: a W-2 paycheck, an 'other' row, a NULL row
        _income(db, a.id, "ACME PAYROLL", 999999, "2026-01-31", "w2")
        _income(db, a.id, "Interest", 5000, "2026-02-28", "other")
        _income(db, a.id, "Mystery", 12345, "2026-03-01", None)

        by_month = monthly_self_employment_income_cents(db, u.id)
        assert by_month == {
            "2026-01": 800000,
            "2026-02": 200000,
            "2026-03": 600000,
        }

    def test_recommend_for_user_end_to_end(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        for i, (month, amt) in enumerate(
            [("2026-01", 900000), ("2026-02", 100000), ("2026-03", 800000),
             ("2026-04", 200000)]
        ):
            _income(db, a.id, f"Client {i}", amt, f"{month}-10", "self_employment")
        rec = recommend_for_user(db, u.id)
        assert rec.sufficient_data is True
        assert rec.recommended_buffer_cents > 0
        # Deterministic.
        assert (
            recommend_for_user(db, u.id).recommended_buffer_cents
            == rec.recommended_buffer_cents
        )

    def test_flat_self_employment_income_zero_buffer(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        for month in ("2026-01", "2026-02", "2026-03", "2026-04"):
            _income(db, a.id, "Retainer", 500000, f"{month}-10", "self_employment")
        rec = recommend_for_user(db, u.id)
        assert rec.sufficient_data is True
        assert rec.recommended_buffer_cents == 0


# ── apply (the one-tap accept) ───────────────────────────────────────────────

class TestApply:
    def test_apply_writes_s2s_buffer(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        series = [900000, 100000, 800000, 200000, 700000, 300000]
        for i, amt in enumerate(series):
            _income(db, a.id, f"C{i}", amt, f"2026-0{i+1}-10", "self_employment")
        rec = recommend_for_user(db, u.id)
        assert u.s2s_buffer == 0  # not auto-applied
        new_buffer = apply_recommendation(db, u.id, rec)
        assert new_buffer == rec.recommended_buffer_cents
        assert u.s2s_buffer == rec.recommended_buffer_cents
