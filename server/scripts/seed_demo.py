"""Seed the database with the canonical demo showcase account.

Run:  DEMO_MODE_ENABLED=true ./.venv/bin/python -m server.scripts.seed_demo

Creates (or resets) the single ``demo`` account and fills it with plentiful,
realistic mock data that exercises every feature of the app at its finest:
accounts, ~12 months of income (W-2 bi-weekly + lumpy self-employment), ~6 months
of categorized spending with a deliberate regime-shift and subscription price
creep, budgets, goals + earmarks, balance snapshots, liabilities, merchant
lifecycle, the tax layer, scenarios + a plan of record, rules, learned
merchant/memory facts, and notifications. Then it drives the REAL game engine
(backfill + daily/weekly/monthly ticks) so the game layer is event-sourced and
consistent with the append-only invariants.

All money is integer cents; dates are ISO ``YYYY-MM-DD`` strings; the RNG is
seeded so the data is deterministic.

The financial portion is idempotent (``reset_user`` wipes the demo user's owned
rows and reseeds). The game portion is NOT — ``game_events`` / ``runs.map_json``
are append-only (DB triggers block UPDATE/DELETE), so re-running would stack a
second history. For a clean re-seed, run on a FRESH database (see docs/DEMO-MODE.md);
the ``--fresh`` guard refuses the game-layer portion if a demo event stream exists.

Login afterward with  username: demo   password: Demo123!
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select

from server.src.db.session import SessionLocal
from server.src.db.models import (
    Account as AccountORM,
    BalanceSnapshot as BalanceSnapshotORM,
    Budget as BudgetORM,
    CategorySettings as CategorySettingsORM,
    Earmark as EarmarkORM,
    Expense as ExpenseORM,
    GameEvent as GameEventORM,
    Goal as GoalORM,
    Income as IncomeORM,
    Liability as LiabilityORM,
    LiabilityAdjustment as LiabilityAdjustmentORM,
    MerchantCategory as MerchantCategoryORM,
    MerchantLifecycle as MerchantLifecycleORM,
    MerchantTaxBucket as MerchantTaxBucketORM,
    MileageLog as MileageLogORM,
    Notification as NotificationORM,
    PlanOfRecord as PlanOfRecordORM,
    Rule as RuleORM,
    RuleExecution as RuleExecutionORM,
    Scenario as ScenarioORM,
    TaxDocument as TaxDocumentORM,
    TaxTag as TaxTagORM,
    User as UserORM,
    UserMemory as UserMemoryORM,
)
from server.src.models import NewUser
from server.src.services.auth_service import AuthService
from server.src.services.scenario_overlay import (
    DiscreteFlow,
    RecurringAdd,
    ScenarioOverlay,
    overlay_to_json,
)
from server.src.services.tax.buckets import canonicalize_bucket, default_deductible_bps

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed_demo")

RNG = random.Random(20260619)  # deterministic data

DEMO = {
    "username": "demo",
    "email": "demo@example.com",
    "full_name": "Demo Saver",
    "password": "Demo123!",
}

# (title, category, low$, high$) — discretionary spend, drawn each occurrence.
DISCRETIONARY = [
    ("Whole Foods", "Food", 28, 92),
    ("Trader Joe's", "Food", 22, 70),
    ("Chipotle", "Food and Drink", 11, 26),
    ("Blue Bottle Coffee", "Food and Drink", 5, 14),
    ("Uber", "Transportation", 9, 38),
    ("Shell Gas", "Transportation", 32, 64),
    ("Amazon", "Shops", 15, 130),
    ("Target", "Shops", 24, 110),
    ("AMC Theatres", "Entertainment", 16, 44),
    ("Steam", "Entertainment", 8, 60),
    ("Walgreens", "Service", 7, 40),
    ("Delta Air Lines", "Travel", 120, 380),
]

# (title, category, $amount, day-of-month) — fixed recurring bills.
MONTHLY_BILLS = [
    ("Rent", "Housing", 1850.00, 1),
    ("PG&E Electric", "Utilities", 120.00, 8),
    ("Comcast Internet", "Utilities", 79.99, 12),
    ("Geico Auto Insurance", "Service", 142.00, 15),
    ("Netflix", "Entertainment", 15.49, 17),
    ("Spotify", "Entertainment", 11.99, 22),
    ("Planet Fitness", "Service", 24.99, 25),
]


def cents(dollars: float) -> int:
    return int(round(dollars * 100))


def _month_starts(start: date, end: date):
    """Yield the first-of-month date for every month in [start, end]."""
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        yield cursor
        cursor = (cursor.replace(day=28) + timedelta(days=7)).replace(day=1)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

# Every table the seed OWNS by ``user_id``, child-first so explicit deletes don't
# trip a FK even when SQLite FK enforcement is off. Game tables are intentionally
# absent — they're append-only (see module docstring / --fresh guard).
_OWNED_CHILD_FIRST = (
    EarmarkORM,
    RuleExecutionORM,
    RuleORM,
    LiabilityAdjustmentORM,
    LiabilityORM,
    TaxTagORM,
    MerchantTaxBucketORM,
    TaxDocumentORM,
    MileageLogORM,
    PlanOfRecordORM,
    ScenarioORM,
    MerchantLifecycleORM,
    MerchantCategoryORM,
    NotificationORM,
    UserMemoryORM,
    BalanceSnapshotORM,
    BudgetORM,
    GoalORM,
    ExpenseORM,
    IncomeORM,
    AccountORM,
)


def reset_user(db, user_id: int) -> None:
    """Wipe every financial/showcase row the demo user owns (NOT game events)."""
    for model in _OWNED_CHILD_FIRST:
        db.execute(delete(model).where(model.user_id == user_id))


# ---------------------------------------------------------------------------
# Part B — financial / showcase domains
# ---------------------------------------------------------------------------


def seed_user_config(user: UserORM) -> None:
    """Give the saver a realistic, feature-exercising profile."""
    user.game_mode = "full"
    user.savings_percent = 15
    user.spend_warning = 20
    user.s2s_include_income = 1
    user.s2s_include_goals = 1
    user.s2s_buffer = cents(50.0)  # $50 safety buffer (stored as cents)
    user.birth_year = 1992


def seed_accounts(db, user: UserORM) -> dict:
    checking = AccountORM(
        name="Everyday Checking", type="checking",
        balance=cents(4800.00), user_id=user.id, last_updated=datetime.now(),
    )
    savings = AccountORM(
        name="High-Yield Savings", type="savings",
        balance=cents(24000.00), user_id=user.id, last_updated=datetime.now(),
    )
    credit = AccountORM(
        name="Sapphire Credit Card", type="credit",
        balance=cents(-842.13), user_id=user.id, last_updated=datetime.now(),
    )
    db.add_all([checking, savings, credit])
    db.flush()
    return {"checking": checking, "savings": savings, "credit": credit}


def seed_income(db, user: UserORM, accounts: dict, start: date, today: date) -> int:
    """Bi-weekly W-2 payroll + lumpy self-employment (CoV > 0.8) + a couple other."""
    checking = accounts["checking"]
    n = 0

    # Bi-weekly W-2 paycheck — the Safe-to-Spend / budget engine keys off this.
    pay_day = start
    while pay_day <= today:
        db.add(IncomeORM(
            title="Acme Corp Payroll", amount=cents(2650.00),
            date=pay_day.isoformat(), category="Work", recurrence="bi-weekly",
            source_type="w2", account_id=checking.id, user_id=user.id,
        ))
        n += 1
        pay_day += timedelta(days=14)

    # Lumpy self-employment income (high coefficient of variation so the income
    # volatility buffer recommends a real number). Amounts deliberately spread
    # across an order of magnitude.
    se_amounts = [180, 2400, 420, 1850, 150, 3100, 260, 900, 2050, 320]
    for amt in se_amounts:
        d = start + timedelta(days=RNG.randint(10, (today - start).days - 5))
        db.add(IncomeORM(
            title="Freelance — design retainer", amount=cents(amt),
            date=d.isoformat(), category="Work", source_type="self_employment",
            account_id=checking.id, user_id=user.id,
        ))
        n += 1

    # A couple of "other" inflows (a refund, a gift).
    for title, amt, days_ago in [("Tax refund", 740, 200), ("Birthday gift", 200, 45)]:
        d = today - timedelta(days=days_ago)
        if d >= start:
            db.add(IncomeORM(
                title=title, amount=cents(amt), date=d.isoformat(),
                category="Other", source_type="other",
                account_id=checking.id, user_id=user.id,
            ))
            n += 1
    return n


def seed_expenses(db, user: UserORM, accounts: dict, start: date, today: date) -> tuple[int, dict]:
    """Recurring bills + dense discretionary (regime-shift) + subscriptions.

    Returns ``(count, tax_refs)`` where tax_refs maps a label → expense id for the
    tax layer to tag (office/vehicle/meals/travel).
    """
    checking = accounts["checking"]
    credit = accounts["credit"]
    n = 0
    # The spending regime shifts up ~$465/mo partway through so the forecast's
    # change-point detector has something real to find.
    shift_date = today - timedelta(days=90)

    # --- Monthly recurring bills -------------------------------------------
    for first in _month_starts(start, today):
        for title, cat, amt, dom in MONTHLY_BILLS:
            try:
                bill_date = first.replace(day=dom)
            except ValueError:
                continue
            if start <= bill_date <= today:
                db.add(ExpenseORM(
                    title=title, amount=cents(amt), date=bill_date.isoformat(),
                    category=cat, recurrence="monthly",
                    account_id=checking.id, user_id=user.id,
                ))
                n += 1

    # --- Subscriptions: one with a price hike, one that goes dormant -------
    for first in _month_starts(start, today):
        # Adobe Creative Cloud — price creep in the last ~2 months.
        adobe_date = first.replace(day=5)
        if start <= adobe_date <= today:
            price = 59.99 if adobe_date >= shift_date else 52.99
            db.add(ExpenseORM(
                title="Adobe Creative Cloud", amount=cents(price),
                date=adobe_date.isoformat(), category="Service", recurrence="monthly",
                account_id=credit.id, user_id=user.id,
            ))
            n += 1
        # Hulu — dormant: charges stop ~100 days ago.
        hulu_date = first.replace(day=9)
        if start <= hulu_date <= (today - timedelta(days=100)):
            db.add(ExpenseORM(
                title="Hulu", amount=cents(17.99), date=hulu_date.isoformat(),
                category="Entertainment", recurrence="monthly",
                account_id=credit.id, user_id=user.id,
            ))
            n += 1

    # --- Discretionary spend --------------------------------------------------
    # Three regimes so the data tells a story the engine can read:
    #   * baseline before the shift,
    #   * a sustained step-up at ``shift_date`` (the forecast change-point detector
    #     keys off this), running through the prior month, then
    #   * a deliberately LIGHT current calendar month, so the gamified daily-close
    #     verdicts trend GREEN and the streak is real (the saver "turned a corner").
    day = start
    while day <= today:
        current_month = day.year == today.year and day.month == today.month
        post_shift = day >= shift_date
        if current_month:
            hi, scale = 1, 0.65          # light: under budget pace ⇒ GREEN days
        elif post_shift:
            hi, scale = 4, 1.18          # the step-up regime
        else:
            hi, scale = 3, 1.0           # baseline
        for _ in range(RNG.randint(0, hi)):
            title, cat, lo, ceil = RNG.choice(DISCRETIONARY)
            if current_month and cat == "Travel":
                continue                  # no big-ticket Travel in the clean month
            amt = RNG.uniform(lo, ceil) * scale
            acct = credit if RNG.random() < 0.6 else checking
            db.add(ExpenseORM(
                title=title, amount=cents(amt), date=day.isoformat(),
                category=cat, account_id=acct.id, user_id=user.id,
            ))
            n += 1
        day += timedelta(days=1)

    # --- Deliberate business expenses we can tag for the tax layer ----------
    tax_refs: dict = {}
    business = [
        ("office", "Staples — printer & supplies", "Shops", 184.20, 60),
        ("vehicle", "Shell Gas — client visit", "Transportation", 58.40, 40),
        ("meals", "Client lunch — Tartine", "Food and Drink", 96.00, 30),
        ("travel", "Delta — conference flight", "Travel", 342.00, 75),
    ]
    for label, title, cat, amt, days_ago in business:
        d = today - timedelta(days=days_ago)
        if d < start:
            d = start
        exp = ExpenseORM(
            title=title, amount=cents(amt), date=d.isoformat(),
            category=cat, account_id=credit.id, user_id=user.id,
        )
        db.add(exp)
        db.flush()  # assign id so the tax layer can tag it
        tax_refs[label] = exp.id
        n += 1

    return n, tax_refs


def seed_budgets(db, user: UserORM) -> None:
    """~8 envelope budgets: mixed over/under/on-pace, rollover on a few."""
    # Essentials (Food/Transportation/Service/Utilities/Housing) may run over and
    # it's fine — they never MISS a gamified day. The discretionary envelopes
    # (Entertainment/Shops/Travel/Food and Drink) are kept generous so the light
    # current month stays on pace and the streak is real.
    budgets = [
        ("Food", 600, 0),               # essential — can show over
        ("Food and Drink", 280, 1),     # discretionary — generous
        ("Transportation", 260, 0),     # essential
        ("Entertainment", 160, 1),      # discretionary — generous
        ("Shops", 360, 0),              # discretionary — generous
        ("Service", 260, 0),            # essential — recurring bills can run it over
        ("Utilities", 240, 0),          # essential
        ("Travel", 240, 1),             # discretionary — no current-month travel
    ]
    for cat, limit, rollover in budgets:
        db.add(BudgetORM(
            user_id=user.id, category=cat,
            monthly_limit=cents(limit), rollover=rollover,
        ))


def seed_goals_and_earmarks(db, user: UserORM, today: date) -> None:
    """5–6 goals at varied progress + earmarks partitioning the Emergency Fund."""
    emergency = GoalORM(
        name="Emergency Fund", description="6 months of essentials",
        amount=cents(15000.00), progress=cents(10500.00),  # 70%
        date=(today + timedelta(days=210)).isoformat(), completed=0, user_id=user.id,
    )
    goals = [
        emergency,
        GoalORM(
            name="House Down Payment", description="20% on a starter home",
            amount=cents(60000.00), progress=cents(6000.00),  # 10%, long horizon
            date=(today + timedelta(days=2900)).isoformat(), completed=0, user_id=user.id,
        ),
        GoalORM(
            name="Japan Trip", description="Two weeks, spring",
            amount=cents(6000.00), progress=cents(1200.00),  # 20%
            date=(today + timedelta(days=300)).isoformat(), completed=0, user_id=user.id,
        ),
        GoalORM(
            name="New Laptop", description="M-series upgrade",
            amount=cents(2200.00), progress=cents(2134.00),  # 97%
            date=(today + timedelta(days=40)).isoformat(), completed=0, user_id=user.id,
        ),
        GoalORM(
            name="Camera Kit", description="Mirrorless + lens",
            amount=cents(1800.00), progress=cents(1800.00),  # completed
            date=(today - timedelta(days=12)).isoformat(), completed=1, user_id=user.id,
        ),
    ]
    db.add_all(goals)
    db.flush()  # assign ids

    # Earmarks partition part of the Emergency Fund's progress (sum <= progress).
    for name, amt in [("Rent buffer", 4500.00), ("Medical", 2000.00), ("Car repair", 1500.00)]:
        db.add(EarmarkORM(
            goal_id=emergency.id, user_id=user.id,
            name=name, amount_cents=cents(amt),
        ))


def seed_balance_snapshots(db, user: UserORM, start: date, today: date) -> None:
    """One net-worth snapshot per day, gentle uptrend with mild noise."""
    base = 24_500.00  # starting net worth in dollars (≈ liquid assets)
    day = start
    i = 0
    while day <= today:
        drift = i * 11.0  # ~$11/day uptrend
        noise = RNG.uniform(-120, 120)
        total = base + drift + noise
        db.add(BalanceSnapshotORM(
            user_id=user.id, date=day.isoformat(), total=cents(total),
        ))
        day += timedelta(days=1)
        i += 1


def seed_liabilities(db, user: UserORM, accounts: dict) -> None:
    """Credit-card concentration boss + a car loan + a student loan; adjustments."""
    cc = LiabilityORM(
        user_id=user.id, name="Sapphire Credit Card", kind="credit_card",
        principal_cents=cents(842.13), apr_bps=2399, minimum_payment_cents=cents(35.00),
        due_day=18, linked_account_id=accounts["credit"].id,
        status="active", is_active_boss=1, ordering_choice="avalanche",
    )
    car = LiabilityORM(
        user_id=user.id, name="Auto Loan — Civic", kind="loan",
        principal_cents=cents(11_400.00), apr_bps=649, minimum_payment_cents=cents(312.00),
        due_day=5, status="active", is_active_boss=0, ordering_choice="avalanche",
    )
    student = LiabilityORM(
        user_id=user.id, name="Student Loan", kind="loan",
        principal_cents=cents(18_950.00), apr_bps=468, minimum_payment_cents=cents(210.00),
        due_day=21, status="active", is_active_boss=0, ordering_choice="snowball",
    )
    db.add_all([cc, car, student])
    db.flush()

    # A couple of manual reconciliation adjustments.
    db.add(LiabilityAdjustmentORM(
        liability_id=car.id, user_id=user.id,
        delta_cents=cents(-312.00), reason="Monthly payment",
    ))
    db.add(LiabilityAdjustmentORM(
        liability_id=cc.id, user_id=user.id,
        delta_cents=cents(120.00), reason="Interest accrual",
    ))


def seed_merchant_lifecycle(db, user: UserORM, today: date) -> None:
    """BG/NBD-style lifecycle snapshots spanning active / lapsing / dormant."""
    iso = today.isoformat()
    rows = [
        # active subscription, steady cadence
        dict(merchant="netflix", title="Netflix", probability_alive=0.98,
             expected_purchases=1.0, status="active", cadence="monthly", n_charges=6,
             last_amount=cents(15.49), prev_amount=cents(15.49), price_change_pct=0.0,
             last_date=iso),
        # active with a price hike
        dict(merchant="adobe creative cloud", title="Adobe Creative Cloud",
             probability_alive=0.95, expected_purchases=1.0, status="active",
             cadence="monthly", n_charges=6, last_amount=cents(59.99),
             prev_amount=cents(52.99), price_change_pct=0.132, last_date=iso),
        # lapsing — probability dropping
        dict(merchant="planet fitness", title="Planet Fitness", probability_alive=0.55,
             expected_purchases=0.4, status="lapsing", cadence="monthly", n_charges=5,
             last_amount=cents(24.99), prev_amount=cents(24.99), price_change_pct=0.0,
             last_date=(today - timedelta(days=38)).isoformat()),
        # dormant — likely cancelled, hasn't charged in 100+ days
        dict(merchant="hulu", title="Hulu", probability_alive=0.08,
             expected_purchases=0.02, status="dormant", cadence="monthly", n_charges=4,
             last_amount=cents(17.99), prev_amount=cents(17.99), price_change_pct=0.0,
             last_date=(today - timedelta(days=104)).isoformat()),
    ]
    for r in rows:
        db.add(MerchantLifecycleORM(user_id=user.id, fitted_at=iso, **r))


def seed_tax(db, user: UserORM, tax_refs: dict, today: date) -> None:
    """Schedule-C tags, tax documents, mileage logs, merchant→bucket mappings."""
    year = today.year

    def _tag(label: str, bucket_key: str) -> None:
        exp_id = tax_refs.get(label)
        if exp_id is None:
            return
        bucket = canonicalize_bucket(bucket_key)
        if bucket is None:
            logger.warning("tax: unknown bucket %s — skipped", bucket_key)
            return
        db.add(TaxTagORM(
            user_id=user.id, tx_type="expense", tx_id=exp_id, tax_year=year,
            bucket=bucket, business_personal="business",
            deductible_bps=default_deductible_bps(bucket), source="user",
        ))

    _tag("office", "sch_c_18_office")
    _tag("vehicle", "sch_c_9_car_truck")
    _tag("meals", "sch_c_24b_meals")     # 50% deductible by default
    _tag("travel", "sch_c_24a_travel")

    # Tax documents: a confirmed W-2, a pending 1099-NEC, a mortgage 1098.
    db.add(TaxDocumentORM(
        user_id=user.id, tax_year=year, form_type="W-2",
        issuer_name="Acme Corp", issuer_tin_last4="4821",
        fields_json=json.dumps({"box1_wages_cents": cents(68900.00),
                                "box2_fed_withheld_cents": cents(9100.00)}),
        status="confirmed", source_kind="image",
        confirmed_at=datetime.now(),
    ))
    db.add(TaxDocumentORM(
        user_id=user.id, tax_year=year, form_type="1099-NEC",
        issuer_name="Bright Studio LLC", issuer_tin_last4="3370",
        fields_json=json.dumps({"box1_nonemployee_comp_cents": cents(11500.00)}),
        status="pending_review", source_kind="pdf",
    ))
    db.add(TaxDocumentORM(
        user_id=user.id, tax_year=year, form_type="1098",
        issuer_name="Coastal Mortgage", issuer_tin_last4="9912",
        fields_json=json.dumps({"box1_mortgage_interest_cents": cents(8400.00)}),
        status="pending_review", source_kind="pdf",
    ))

    # Mileage logs (miles × 1000 = miles_milli).
    for days_ago, miles, purpose in [
        (70, 42.5, "Client site — onboarding"),
        (54, 18.0, "Supply run"),
        (39, 63.2, "Conference"),
        (22, 12.4, "Client lunch"),
        (8, 27.6, "Vendor meeting"),
    ]:
        d = today - timedelta(days=days_ago)
        db.add(MileageLogORM(
            user_id=user.id, trip_date=d.isoformat(),
            miles_milli=int(round(miles * 1000)), purpose=purpose,
            business_personal="business", tax_year=d.year,
        ))

    # Learned merchant → tax-bucket mappings.
    for merchant, bucket_key in [
        ("staples", "sch_c_18_office"),
        ("delta air lines", "sch_c_24a_travel"),
    ]:
        bucket = canonicalize_bucket(bucket_key)
        if bucket:
            db.add(MerchantTaxBucketORM(
                user_id=user.id, merchant=merchant, bucket=bucket, source="user",
            ))


def seed_scenarios(db, user: UserORM, today: date) -> None:
    """Two valid scenarios + one committed plan of record."""
    # "Freelance full-time": drop the W-2, add a larger recurring self-employment
    # stream, and a discrete equipment purchase.
    freelance = ScenarioOverlay(
        added_recurring=(
            RecurringAdd(
                title="Full-time freelance", amount_cents=cents(5200.00),
                recurrence="monthly", kind="income", category="Work",
                anchor_date=today.isoformat(),
            ),
        ),
        discrete_flows=(
            DiscreteFlow(
                date=(today + timedelta(days=30)).isoformat(),
                amount_cents=cents(2400.00), kind="expense",
                title="Workstation upgrade", category="Shops",
            ),
        ),
        config_overrides={"label": "Freelance full-time"},
    )
    # "Emergency-fund boost": nudge the Emergency Fund target up.
    boost = ScenarioOverlay(
        added_recurring=(
            RecurringAdd(
                title="Extra EF transfer", amount_cents=cents(400.00),
                recurrence="monthly", kind="expense", category="Transfer",
                anchor_date=today.isoformat(),
            ),
        ),
        config_overrides={"label": "Emergency-fund boost"},
    )

    s1 = ScenarioORM(
        user_id=user.id, name="Freelance full-time",
        overlay_json=json.dumps(overlay_to_json(freelance)),
    )
    s2 = ScenarioORM(
        user_id=user.id, name="Emergency-fund boost",
        overlay_json=json.dumps(overlay_to_json(boost)),
    )
    db.add_all([s1, s2])
    db.flush()

    # One committed plan of record pinned to the boost scenario.
    db.add(PlanOfRecordORM(
        user_id=user.id, scenario_id=s2.id,
        rule_ids_json=json.dumps([]),
        baseline_snapshot_json=json.dumps({
            "as_of": today.isoformat(),
            "net_worth_cents": cents(13_828.42),
            "monthly_savings_cents": cents(400.00),
        }),
        status="active",
    ))


def seed_rules(db, user: UserORM) -> None:
    """Three automation rules + a couple of idempotency-log executions."""
    notify_rule = RuleORM(
        user_id=user.id, name="Big purchase heads-up", enabled=1,
        conditions=json.dumps([{"field": "amount_cents", "op": ">=", "value": cents(200.00)}]),
        action_type="notify", action_params=json.dumps({"message": "Large purchase posted"}),
        priority=10,
    )
    roundup_rule = RuleORM(
        user_id=user.id, name="Round-ups to savings", enabled=1,
        conditions=json.dumps([{"field": "category", "op": "in",
                                "value": ["Food", "Food and Drink", "Shops"]}]),
        action_type="roundup", action_params=json.dumps({"to_account": "savings"}),
        priority=5,
    )
    categorize_rule = RuleORM(
        user_id=user.id, name="Tag Adobe as a tool", enabled=1,
        conditions=json.dumps([{"field": "title", "op": "contains", "value": "Adobe"}]),
        action_type="categorize", action_params=json.dumps({"category": "Service"}),
        priority=1,
    )
    db.add_all([notify_rule, roundup_rule, categorize_rule])
    db.flush()

    # A couple of historical firings (dedup log).
    db.add(RuleExecutionORM(
        rule_id=notify_rule.id, user_id=user.id, tx_type="expense", tx_id=1,
        action_type="notify", amount_cents=cents(342.00), result="ok",
    ))
    db.add(RuleExecutionORM(
        rule_id=roundup_rule.id, user_id=user.id, tx_type="expense", tx_id=2,
        action_type="roundup", amount_cents=cents(0.62), result="ok",
    ))


def seed_misc(db, user: UserORM) -> None:
    """Learned merchant categories, durable memory facts, category flags, notices."""
    # Merchant → category learned mappings.
    for merchant, cat in [
        ("blue bottle coffee", "Food and Drink"),
        ("shell gas", "Transportation"),
        ("steam", "Entertainment"),
        ("whole foods", "Food"),
    ]:
        db.add(MerchantCategoryORM(
            user_id=user.id, merchant=merchant, category=cat, source="user",
        ))

    # Durable memory facts (closed key slugs; see services/user_memory.MEMORY_KEYS).
    now_iso = datetime.now().isoformat()
    facts = [
        ("savings_intent", "Saving for a house down payment by 2028", "user", 100, 1),
        ("income_cadence", "Payroll lands every other Friday; freelance is lumpy", "deterministic", 90, 0),
        ("tone_preference", "plain", "user", 100, 0),
        ("essential_category", "Housing", "user", 100, 0),
    ]
    for key, value, source, conf, pinned in facts:
        db.add(UserMemoryORM(
            user_id=user.id, key=key, value=value, source=source,
            confidence=conf, pinned=pinned, created_at=now_iso, updated_at=now_iso,
        ))

    # Category settings (essentials). PK is the category name (global, not per-user),
    # so upsert idempotently rather than relying on reset_user.
    # Recurring-bill categories (Service = insurance/subscriptions, Utilities) are
    # essential: their bills can run a category over pace without it counting as a
    # gamified MISS. Discretionary categories drive the green-day verdict.
    for name, essential in [
        ("Housing", 1), ("Utilities", 1), ("Food", 1), ("Transportation", 1),
        ("Service", 1), ("Entertainment", 0), ("Shops", 0), ("Travel", 0),
        ("Food and Drink", 0),
    ]:
        existing = db.get(CategorySettingsORM, name)
        if existing is None:
            db.add(CategorySettingsORM(name=name, essential=essential, user_confirmed=1))
        else:
            existing.essential = essential
            existing.user_confirmed = 1

    # Notifications: a mix of read/unread with stable dedup refs.
    notices = [
        ("anomaly", "Unusual spend in Travel", "A $342 Travel charge is above your usual.", "anomaly:Travel:flight", 0),
        ("budget_overrun", "Entertainment over budget", "You're 18% over your Entertainment envelope.", "budget_overrun:Entertainment:this-month", 0),
        ("price_creep", "Adobe raised its price", "Adobe Creative Cloud went from $52.99 to $59.99.", "price_creep:adobe", 0),
        ("zombie_sub", "Hulu looks dormant", "No Hulu charge in 100+ days — cancel?", "lifecycle:hulu:dormant", 1),
        ("overdraft_risk", "Tight week ahead", "Projected balance dips low before payday.", "overdraft:this-week", 0),
        ("goal", "Laptop goal almost there", "You're 97% to your New Laptop goal.", "goal:new-laptop:97", 1),
    ]
    for typ, title, msg, ref, read in notices:
        db.add(NotificationORM(
            user_id=user.id, type=typ, title=title, message=msg, ref=ref, read=read,
        ))


# ---------------------------------------------------------------------------
# Part C — event-sourced game layer (drive the REAL engine)
# ---------------------------------------------------------------------------


def demo_game_stream_exists(db) -> bool:
    """True if a demo game-event history already exists (append-only — see docs)."""
    count = db.execute(select(func.count(GameEventORM.id))).scalar_one()
    return bool(count)


def seed_game_layer(db, today: date) -> None:
    """Drive backfill + daily/weekly/monthly ticks so events arise legitimately.

    Never fabricates an event stream from rows: it invokes the engine's own
    machinery, which folds synchronously into the projections.
    """
    from server.src.services.game.backfill import run_backfill
    from server.src.services.game.daily import DailyService, streak_view
    from server.src.services.game.expedition import RunService
    from server.src.scheduler import run_due_game_jobs

    auth = AuthService()
    user = auth.get_user(db, DEMO["username"])
    if user is None:
        raise RuntimeError("demo user missing — financial seed must run first")

    # 1) Baseline snapshot (idempotent).
    run_backfill(db)
    db.commit()

    # 2) Draft an Expedition Run for every month in the window (incl. the current,
    #    in-progress one). Production drafts a run at month start; the month-close
    #    seal NO-OPS without one, so the demo must draft them up front.
    runs = RunService(db)
    drafted = 0
    for first in _month_starts(today - timedelta(days=365), today):
        try:
            runs.draft(user, first.strftime("%Y-%m"))
            drafted += 1
        except Exception as exc:
            logger.warning("game: run draft %s skipped: %s", first, exc)
            db.rollback()
    db.commit()

    # 3) Daily closes over the recent window so the streak machine has real days
    #    (the current month is light by design ⇒ GREEN days ⇒ a real streak).
    daily = DailyService(db)
    day = today - timedelta(days=40)
    closed = 0
    while day < today:
        try:
            daily.close_day(user, day)
            closed += 1
        except Exception as exc:  # best-effort: a single bad day must not abort
            logger.warning("game: close_day(%s) skipped: %s", day, exc)
            db.rollback()
        day += timedelta(days=1)
    db.commit()

    # 4) Monthly closes for every fully-completed past month, chronologically, so
    #    each drafted Run is sealed by the real month-close path.
    first_of_this_month = date(today.year, today.month, 1)
    sealed = 0
    for first in _month_starts(today - timedelta(days=365), today):
        if first <= date(today.year, today.month, 1) and first != first_of_this_month:
            # run_due_game_jobs seals the month that ENDED before ``first``.
            try:
                run_due_game_jobs(db, first)
                db.commit()
                sealed += 1
            except Exception as exc:
                logger.warning("game: month tick %s skipped: %s", first, exc)
                db.rollback()

    # 4) Final weekly rollups + fade as of today.
    try:
        run_due_game_jobs(db, today)
        db.commit()
    except Exception as exc:
        logger.warning("game: final weekly tick skipped: %s", exc)
        db.rollback()

    view = streak_view(db)
    logger.info(
        "game: backfilled; %d days closed, %d month ticks; streak current=%s best=%s",
        closed, sealed, view.get("current"), view.get("best"),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def main(fresh: bool = False) -> None:
    db = SessionLocal()
    try:
        auth = AuthService()
        user = db.execute(
            select(UserORM).where(UserORM.username == DEMO["username"])
        ).scalar_one_or_none()

        if user is None:
            auth.create_user(db, NewUser(**DEMO))
            db.flush()
            user = db.execute(
                select(UserORM).where(UserORM.username == DEMO["username"])
            ).scalar_one()
            logger.info("created user '%s'", DEMO["username"])
        else:
            reset_user(db, user.id)
            logger.info("reset existing user '%s' (financial rows)", DEMO["username"])

        today = date.today()
        start = today - timedelta(days=365)  # ~12 months of income history
        exp_start = today - timedelta(days=185)  # ~6 months of spending

        # --- Part B: financial / showcase domains --------------------------
        seed_user_config(user)
        accounts = seed_accounts(db, user)
        n_inc = seed_income(db, user, accounts, start, today)
        n_exp, tax_refs = seed_expenses(db, user, accounts, exp_start, today)
        seed_budgets(db, user)
        seed_goals_and_earmarks(db, user, today)
        seed_balance_snapshots(db, user, exp_start, today)
        seed_liabilities(db, user, accounts)
        seed_merchant_lifecycle(db, user, today)
        seed_tax(db, user, tax_refs, today)
        seed_scenarios(db, user, today)
        seed_rules(db, user)
        seed_misc(db, user)
        db.commit()
        logger.info(
            "seeded financials: 3 accounts, %d expenses, %d income, goals/budgets/"
            "liabilities/tax/scenarios/rules/notifications", n_exp, n_inc,
        )

        # --- Part C: event-sourced game layer ------------------------------
        if demo_game_stream_exists(db):
            if fresh:
                raise SystemExit(
                    "Refusing --fresh game seed: a demo game_events stream already "
                    "exists and is append-only. Re-seed on a FRESH database "
                    "(see docs/DEMO-MODE.md)."
                )
            logger.info(
                "game: a demo event stream already exists — skipping the game layer "
                "(append-only). Financials were reseeded. Use a fresh DB for a clean "
                "game history."
            )
        else:
            seed_game_layer(db, today)

        logger.info("done. login →  username: demo   password: Demo123!")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the demo showcase account.")
    parser.add_argument(
        "--fresh", action="store_true",
        help="Require a clean game history; refuse if a demo event stream exists.",
    )
    args = parser.parse_args()
    main(fresh=args.fresh)
