"""Discretionary-burn unit + integration tests (HistAvg).

The forecast can drain an estimated daily discretionary burn (non-recurring
spend) so the trough reflects ordinary day-to-day spending, not just scheduled
bills. ``hist_avg_daily_burn_cents`` is the pure estimator; the integration
tests confirm it flows through ``forecast(include_burn=True)``.
"""

import random
from datetime import date

from server.src.db.models import Account, Expense, Income, User
from server.src.services.forecast_service import (
    ForecastService,
    hist_avg_daily_burn_cents,
)
from server.src.services.scenario_overlay import (
    DiscreteFlow,
    ScenarioOverlay,
)


# ── pure estimator ─────────────────────────────────────────────────────────


def test_hist_avg_drops_top_decile_then_divides_by_window():
    # 10 txns 100..1000 cents, window 10 days. floor(10*0.10)=1 dropped (the
    # 1000). Sum kept = 100+...+900 = 4500. 4500/10 = 450 cents/day.
    amounts = [i * 100 for i in range(1, 11)]
    assert hist_avg_daily_burn_cents(amounts, 10) == 450


def test_hist_avg_below_min_txns_is_zero():
    # Fewer than 3 transactions → can't infer a rate → 0.
    assert hist_avg_daily_burn_cents([5000, 5000], 30) == 0
    assert hist_avg_daily_burn_cents([5000], 30) == 0


def test_hist_avg_empty_is_zero():
    assert hist_avg_daily_burn_cents([], 30) == 0


def test_hist_avg_zero_window_guards():
    assert hist_avg_daily_burn_cents([100, 100, 100], 0) == 0


def test_hist_avg_no_drop_when_decile_rounds_to_zero():
    # N=9 → floor(9*0.10)=0, nothing dropped. sum=900, /30 = 30 cents/day.
    assert hist_avg_daily_burn_cents([100] * 9, 30) == 30


# ── integration through forecast() ─────────────────────────────────────────


def _seed_user(db_session, balance_cents):
    user = User(username="burn", full_name="Burn U", email="burn@x.com",
                hashed_password="x")
    db_session.add(user)
    db_session.flush()
    acct = Account(name="Checking", type="checking",
                   balance=balance_cents, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def test_forecast_subtracts_daily_burn(db_session):
    """Five non-recurring $30 expenses in the trailing 30 days → burn = sum of
    kept (floor(5*0.1)=0 dropped) / 30 = 15000/30 = 500 cents/day. Over a 10-day
    horizon with no scheduled flows, ending = start - 500*10."""
    user, acct = _seed_user(db_session, 100_000)  # $1,000
    for d in ("2026-02-20", "2026-02-22", "2026-02-24", "2026-02-26", "2026-02-28"):
        db_session.add(Expense(title="Coffee", amount=30_00, date=d,
                               category="Food", account_id=acct.id))
    db_session.flush()

    start, end = date(2026, 3, 1), date(2026, 3, 11)  # 10 days
    out = ForecastService(db_session).forecast(
        user.id, start, end, include_burn=True
    )
    assert out["daily_discretionary_burn"] == 5.0  # 500 cents/day
    # 10 days of $5 burn = $50 drained.
    assert out["total_projected_discretionary"] == 50.0
    assert out["ending_balance"] == 1000.0 - 50.0
    assert out["lowest_balance"] == 950.0


def test_forecast_without_burn_flag_ignores_discretionary(db_session):
    """Same data, include_burn=False (the game-mode path) → no burn, flat."""
    user, acct = _seed_user(db_session, 100_000)
    for d in ("2026-02-20", "2026-02-22", "2026-02-24", "2026-02-26", "2026-02-28"):
        db_session.add(Expense(title="Coffee", amount=30_00, date=d,
                               category="Food", account_id=acct.id))
    db_session.flush()

    out = ForecastService(db_session).forecast(
        user.id, date(2026, 3, 1), date(2026, 3, 11), include_burn=False
    )
    assert out["ending_balance"] == 1000.0
    assert "daily_discretionary_burn" not in out


def test_forecast_reports_overdraft_band_with_seed(db_session):
    """include_burn adds overdraft_probability + an ordered trough_band, and a
    seeded rng makes them reproducible."""
    import random

    user, acct = _seed_user(db_session, 6_000)  # $60
    for d in ("2026-02-18", "2026-02-20", "2026-02-22", "2026-02-24", "2026-02-26"):
        db_session.add(Expense(title="Coffee", amount=40_00, date=d,
                               category="Food", account_id=acct.id))
    db_session.flush()
    start, end = date(2026, 3, 1), date(2026, 3, 11)
    svc = ForecastService(db_session)
    a = svc.forecast(user.id, start, end, include_burn=True, rng=random.Random(7))
    b = svc.forecast(user.id, start, end, include_burn=True, rng=random.Random(7))
    assert a["overdraft_probability"] == b["overdraft_probability"]
    assert a["trough_band"] == b["trough_band"]
    band = a["trough_band"]
    assert band["low"] <= band["median"] <= band["high"]
    assert 0.0 <= a["overdraft_probability"] <= 1.0


def test_burn_can_flip_will_go_negative(db_session):
    """A thin balance that survives scheduled-only goes negative once daily burn
    is applied — the whole point of the feature."""
    user, acct = _seed_user(db_session, 4_000)  # $40
    for d in ("2026-02-20", "2026-02-22", "2026-02-24", "2026-02-26", "2026-02-28"):
        db_session.add(Expense(title="Coffee", amount=30_00, date=d,
                               category="Food", account_id=acct.id))
    db_session.flush()
    start, end = date(2026, 3, 1), date(2026, 3, 11)  # 10 days × $5 = $50 > $40
    scheduled = ForecastService(db_session).forecast(
        user.id, start, end, include_burn=False
    )
    burned = ForecastService(db_session).forecast(
        user.id, start, end, include_burn=True
    )
    assert scheduled["will_go_negative"] is False
    assert burned["will_go_negative"] is True


# ── scenario overlay threading (v6 doc 02) ─────────────────────────────────


def _seed_user_with_paycheck(db_session, balance_cents, amount_cents):
    """A user + checking account + a bi-weekly paycheck anchored just before the
    March horizon, so the income shows up in the projection."""
    user, acct = _seed_user(db_session, balance_cents)
    db_session.add(
        Income(
            title="Paycheck",
            amount=amount_cents,
            date="2026-02-28",
            category="Work",
            recurrence="bi-weekly",
            account_id=acct.id,
        )
    )
    db_session.flush()
    return user, acct


def test_forecast_overlay_none_regression_pin(db_session):
    user, acct = _seed_user_with_paycheck(db_session, 100_000, 50_000)
    start, end = date(2026, 3, 1), date(2026, 3, 31)
    svc = ForecastService(db_session)
    plain = svc.forecast(
        user.id, start, end, include_burn=True, rng=random.Random(0)
    )
    overlaid = svc.forecast(
        user.id, start, end, include_burn=True, rng=random.Random(0),
        overlay=ScenarioOverlay(),  # EMPTY-equivalent identity overlay
    )
    assert plain == overlaid


def test_forecast_overlay_balance_override_sets_start(db_session):
    """``balance_override_cents`` replaces the summed account balance as the
    projection's starting point; nothing else about the walk changes."""
    user, _ = _seed_user(db_session, 100_000)  # real balance $1,000
    start, end = date(2026, 3, 1), date(2026, 3, 11)
    svc = ForecastService(db_session)
    out = svc.forecast(
        user.id, start, end,
        overlay=ScenarioOverlay(balance_override_cents=25_000),  # $250
    )
    assert out["starting_balance"] == 250.0
    # No scheduled flows, no burn → ending == starting override.
    assert out["ending_balance"] == 250.0
    assert out["lowest_balance"] == 250.0


def test_forecast_added_income_lifts_trough_and_cuts_overdraft(db_session):
    """An added-income overlay raises ``lowest_balance`` and lowers
    ``overdraft_probability`` versus the same forecast without it (seeded rng so
    the comparison is deterministic — R5)."""
    # Thin balance with a daily burn so there's overdraft risk to move.
    user, acct = _seed_user(db_session, 6_000)  # $60
    for d in ("2026-02-18", "2026-02-20", "2026-02-22", "2026-02-24", "2026-02-26"):
        db_session.add(Expense(title="Coffee", amount=40_00, date=d,
                               category="Food", account_id=acct.id))
    db_session.flush()
    start, end = date(2026, 3, 1), date(2026, 3, 11)
    svc = ForecastService(db_session)

    base = svc.forecast(
        user.id, start, end, include_burn=True, rng=random.Random(3)
    )
    # A one-off $500 deposit on day 2 of the horizon.
    rescue = ScenarioOverlay(
        discrete_flows=(
            DiscreteFlow(date="2026-03-02", amount_cents=50_000, kind="income"),
        )
    )
    lifted = svc.forecast(
        user.id, start, end, include_burn=True, rng=random.Random(3),
        overlay=rescue,
    )
    assert lifted["lowest_balance"] > base["lowest_balance"]
    assert lifted["overdraft_probability"] <= base["overdraft_probability"]


def test_forecast_exposes_trough_band_shape(db_session):
    """Output contract pin (doc 02): include_burn forecasts expose the low-balance
    window the frontend draws as a ReferenceArea — an ordered ``trough_band``
    with low/median/high dollar fields, and a ``lowest_date`` marking the dip."""
    user, acct = _seed_user(db_session, 6_000)
    for d in ("2026-02-18", "2026-02-20", "2026-02-22", "2026-02-24", "2026-02-26"):
        db_session.add(Expense(title="Coffee", amount=40_00, date=d,
                               category="Food", account_id=acct.id))
    db_session.flush()
    out = ForecastService(db_session).forecast(
        user.id, date(2026, 3, 1), date(2026, 3, 11),
        include_burn=True, rng=random.Random(0),
    )
    assert set(out["trough_band"]) == {"low", "median", "high"}
    band = out["trough_band"]
    assert band["low"] <= band["median"] <= band["high"]
    assert "lowest_date" in out and "lowest_balance" in out


def test_daily_contract_handles_horizon_start_and_first_shortfall(db_session):
    user, _ = _seed_user(db_session, 10_000)  # $100
    start, end = date(2026, 3, 1), date(2026, 3, 3)
    overlay = ScenarioOverlay(
        discrete_flows=(
            DiscreteFlow(date=start.isoformat(), amount_cents=15_000, kind="expense", title="Deposit"),
            DiscreteFlow(date="2026-03-02", amount_cents=10_000, kind="income", title="Refund"),
            DiscreteFlow(date=end.isoformat(), amount_cents=30_000, kind="expense", title="Balance due"),
        )
    )
    out = ForecastService(db_session).forecast(
        user.id, start, end, include_burn=True, overlay=overlay
    )
    assert len(out["timeline"]) == 3
    assert out["timeline"][0]["balance"] == -50.0
    assert out["first_negative_date"] == start.isoformat()
    assert out["lowest_date"] == end.isoformat()
    assert len(out["events"]) == 3
    assert out["paths_below_zero"] / out["paths_total"] == out["overdraft_probability"]


def test_consumer_forecast_is_deterministic_without_injected_rng(db_session):
    user, _ = _seed_user(db_session, 10_000)
    svc = ForecastService(db_session)
    first = svc.forecast(user.id, date(2026, 3, 1), date(2026, 3, 31), include_burn=True)
    second = svc.forecast(user.id, date(2026, 3, 1), date(2026, 3, 31), include_burn=True)
    assert first["trough_band"] == second["trough_band"]
    assert first["paths_below_zero"] == second["paths_below_zero"]


def test_same_day_event_preserves_income_and_expense_instead_of_hiding_obligation(db_session):
    user, _ = _seed_user(db_session, 10_000)
    start = date(2026, 3, 1)
    overlay = ScenarioOverlay(
        discrete_flows=(
            DiscreteFlow(date="2026-03-02", amount_cents=20_000, kind="income", title="Paycheck"),
            DiscreteFlow(date="2026-03-02", amount_cents=15_000, kind="expense", title="Rent"),
        )
    )
    out = ForecastService(db_session).forecast(
        user.id, start, date(2026, 3, 3), include_burn=True, overlay=overlay
    )
    assert out["events"] == [
        {
            "date": "2026-03-02",
            "income": 200.0,
            "expenses": 150.0,
            "net": 50.0,
            "label": "Rent, Paycheck",
        }
    ]


# ── A1: residual pool is chronological + day-grouped ────────────────────────


def test_burn_residual_pool_groups_same_day_transactions(db_session):
    """The bootstrap resample pool (``_burn_residual_pool_cents``) must be a
    *daily* series, not the per-transaction amount list: multiple non-recurring
    transactions on the SAME day collapse into one day's total before the
    ``- burn`` deviation, and the pool has exactly ``window_days`` entries (empty
    days contribute ``-burn``). Regression for A1 (was fed the unordered amounts
    list, which defeated the block bootstrap's day-of-week autocorrelation)."""
    user, acct = _seed_user(db_session, 100_000)
    window_days = 7
    as_of = date(2026, 3, 8)  # window = [2026-03-01, 2026-03-08)
    # Three $10 expenses all on a single in-window day (2026-03-02).
    for _ in range(3):
        db_session.add(Expense(title="Coffee", amount=10_00, date="2026-03-02",
                               category="Food", account_id=acct.id))
    db_session.flush()

    svc = ForecastService(db_session)
    burn = 200  # cents/day (arbitrary, for a checkable deviation)
    pool = svc._burn_residual_pool_cents(user.id, as_of, burn, window_days)

    # One entry per window day — never one per transaction.
    assert len(pool) == window_days
    # The 3×$10 collapse to a single 3000-cent day: 3000 - 200 = 2800 appears once.
    assert pool.count(2800) == 1
    # Every other (empty) day is -burn.
    assert pool.count(-burn) == window_days - 1


def test_burn_residual_pool_empty_below_min_txns(db_session):
    """Activity guard preserved: too few non-recurring transactions ⇒ empty pool
    (the simulation collapses to the deterministic walk)."""
    user, acct = _seed_user(db_session, 100_000)
    db_session.add(Expense(title="Coffee", amount=10_00, date="2026-03-02",
                           category="Food", account_id=acct.id))
    db_session.flush()
    pool = ForecastService(db_session)._burn_residual_pool_cents(
        user.id, date(2026, 3, 8), 200, 7
    )
    assert pool == []
