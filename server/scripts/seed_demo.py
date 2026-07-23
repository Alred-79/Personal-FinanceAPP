"""Seed the database with the canonical demo showcase account.

Run:  DEMO_MODE_ENABLED=true ./.venv/bin/python -m server.scripts.seed_demo --bootstrap

Creates the single ``demo`` account (or resets it only with an explicit flag)
and fills it with plentiful,
realistic mock data that exercises every feature of the app at its finest:
accounts, ~12 months of income (W-2 bi-weekly + lumpy self-employment), ~6 months
of categorized spending with a deliberate regime-shift and subscription price
creep, budgets, goals + earmarks, balance snapshots, liabilities, merchant
lifecycle, the tax layer, scenarios + a plan of record, rules, learned
merchant/memory facts, and notifications. Game mode stays off, and no MCP
credential/audit or forecast-calibration/evidence history is invented.

All money is integer cents; dates are ISO ``YYYY-MM-DD`` strings; the RNG is
seeded so the data is deterministic.

``--bootstrap`` is deployment-safe: it seeds only an absent demo user, no-ops
when the canonical seed is already ready, and refuses to mutate an incomplete
existing database. ``--reset-financials`` is the explicit operator-only reset.

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
    ImportRow as ImportRowORM,
    ImportSession as ImportSessionORM,
    Liability as LiabilityORM,
    LiabilityAdjustment as LiabilityAdjustmentORM,
    MerchantCategory as MerchantCategoryORM,
    MerchantAlias as MerchantAliasORM,
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
from server.src.services.demo_readiness import (
    DEMO_DATASET_MARKER_REF,
    DEMO_DATASET_REVISION,
    assess_demo_readiness,
)
from server.src.services.rule_engine import RuleEngine
from server.src.services.merchant_lifecycle_service import (
    MerchantLifecycleService,
    price_creep_pct,
)
from server.src.services.recurring_service import RecurringService, next_occurrence
from server.src.services.categorization_service import normalize_merchant
from server.src.db.rls import set_tenant
from server.src.settings import settings
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
    "full_name": "Maya Chen",
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
    ("Walgreens", "Health", 7, 40),
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
    ("Planet Fitness", "Fitness", 24.99, 25),
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
    ImportRowORM,
    ImportSessionORM,
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
    MerchantAliasORM,
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
    """Give the saver a realistic, feature-exercising profile.

    The demo opens ledger-first. Ambient mode keeps the ordinary Overview as the
    home screen while leaving the fully seeded Expedition available from the
    navigation for visitors who want it. This mirrors the product promise that
    game mechanics are optional, not the identity of the app.
    """
    # Explicit resets must also converge legacy demo identities to the current
    # canonical persona; otherwise a migrated, previously seeded database can
    # pass every financial write and then fail verification on its old name.
    user.full_name = DEMO["full_name"]
    user.email = DEMO["email"]
    user.game_mode = "off"
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
                category="Entertainment", recurrence=None,
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


def seed_goals_and_earmarks(db, user: UserORM, today: date) -> dict[str, GoalORM]:
    """Seven coherent goals, including real targets for the demo rules."""
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
            name="Tax Reserve", description="Set aside 15% of freelance income",
            amount=cents(9000.00), progress=cents(1800.00),
            date=(today + timedelta(days=270)).isoformat(), completed=0, user_id=user.id,
        ),
        GoalORM(
            name="Car Repair Buffer", description="Deductible and major repairs",
            amount=cents(2500.00), progress=cents(900.00),
            date=(today + timedelta(days=365)).isoformat(), completed=0, user_id=user.id,
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
    return {goal.name: goal for goal in goals}


def seed_balance_snapshots(
    db, user: UserORM, start: date, today: date, account_total_cents: int
) -> None:
    """Daily net worth ending exactly at the currently visible account total."""
    base_cents = cents(24_500.00)
    span = max((today - start).days, 1)
    day = start
    i = 0
    while day <= today:
        progress = min(i / span, 1.0)
        trend = round(base_cents + (account_total_cents - base_cents) * progress)
        # Noise fades to zero so the latest point exactly reconciles to Accounts.
        noise = round(RNG.uniform(-12_000, 12_000) * (1.0 - progress))
        total = account_total_cents if day == today else trend + noise
        db.add(BalanceSnapshotORM(
            user_id=user.id, date=day.isoformat(), total=total,
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

    # An auditable payoff ledger: each loan's monthly payment + the card's
    # interest accrual / paydowns across the last 6 months (so the liability
    # history reads as a real running reconciliation, not two lone rows).
    for months_ago in range(6, 0, -1):
        when = datetime.now() - timedelta(days=30 * months_ago)
        db.add(LiabilityAdjustmentORM(
            liability_id=car.id, user_id=user.id,
            delta_cents=cents(-312.00), reason="Monthly payment", created_at=when,
        ))
        db.add(LiabilityAdjustmentORM(
            liability_id=student.id, user_id=user.id,
            delta_cents=cents(-210.00), reason="Monthly payment", created_at=when,
        ))
        db.add(LiabilityAdjustmentORM(
            liability_id=cc.id, user_id=user.id,
            delta_cents=cents(16.84), reason="Interest accrual", created_at=when,
        ))
        db.add(LiabilityAdjustmentORM(
            liability_id=cc.id, user_id=user.id,
            delta_cents=cents(-150.00), reason="Card payment", created_at=when,
        ))


def seed_merchant_lifecycle(db, user: UserORM, today: date) -> None:
    """Modeled showcase states whose observable facts come from real seed rows.

    The lifecycle probability is explicitly modeled output. Dates, counts,
    cadence, amounts, and deterministic price-change arithmetic are all derived
    from the actual transaction history so the UI cannot contradict the ledger.
    """
    summaries = {
        summary.merchant: summary
        for summary in MerchantLifecycleService(db)._summaries(user.id, today, 730)
    }
    modeled = {
        "netflix": (0.98, 1.0, "active"),
        "adobe creative cloud": (0.95, 1.0, "active"),
        "planet fitness": (0.96, 1.0, "active"),
        "hulu": (0.08, 0.02, "dormant"),
    }
    fitted_at = datetime.now().astimezone().isoformat()
    for merchant, (probability, expected, state) in modeled.items():
        summary = summaries.get(merchant)
        if summary is None:
            raise RuntimeError(f"demo lifecycle source transactions missing: {merchant}")
        parsed_last = date.fromisoformat(summary.last_date)
        next_date = next_occurrence(parsed_last, summary.cadence) if summary.cadence else None
        db.add(MerchantLifecycleORM(
            user_id=user.id,
            merchant=merchant,
            title=summary.title,
            probability_alive=probability,
            expected_purchases=expected,
            status=state,
            cadence=summary.cadence,
            n_charges=summary.n_charges,
            last_amount=summary.last_amount,
            prev_amount=summary.prev_amount,
            price_change_pct=price_creep_pct(summary.last_amount, summary.prev_amount),
            last_date=summary.last_date,
            expected_next_date=next_date.isoformat() if next_date else None,
            fitted_at=fitted_at,
        ))


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

    # Tax documents match Maya's actual profile: salaried renter + side work.
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
        user_id=user.id, tax_year=year, form_type="1099-K",
        issuer_name="Stripe Payments", issuer_tin_last4="2048",
        fields_json=json.dumps({"box1a_gross_payments_cents": cents(14250.00)}),
        status="pending_review", source_kind="pdf",
    ))
    db.add(TaxDocumentORM(
        user_id=user.id, tax_year=year, form_type="1098-E",
        issuer_name="Nelnet Servicing", issuer_tin_last4="7731",
        fields_json=json.dumps({"box1_student_loan_interest_cents": cents(890.00)}),
        status="confirmed", source_kind="image", confirmed_at=datetime.now(),
    ))

    # Mileage logs (miles × 1000 = miles_milli) — a steady business-driving log.
    for days_ago, miles, purpose in [
        (96, 51.8, "Client site — kickoff"),
        (84, 22.3, "Supply run — Staples"),
        (70, 42.5, "Client site — onboarding"),
        (61, 14.7, "Bank / post office"),
        (54, 18.0, "Supply run"),
        (47, 88.4, "Client site — out of town"),
        (39, 63.2, "Conference"),
        (31, 9.8, "Client coffee"),
        (22, 12.4, "Client lunch"),
        (15, 36.1, "Vendor warehouse"),
        (8, 27.6, "Vendor meeting"),
        (4, 19.2, "Client site — review"),
        (1, 7.5, "Networking event"),
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


def seed_scenarios(db, user: UserORM, accounts: dict, today: date) -> None:
    """Two honest additive what-ifs + one committed plan of record."""
    # Additive by design: the overlay does not remove Maya's existing W-2 job.
    retainer = ScenarioOverlay(
        added_recurring=(
            RecurringAdd(
                title="New freelance retainer", amount_cents=cents(2000.00),
                recurrence="monthly", kind="income", category="Work",
                anchor_date=today.isoformat(),
            ),
        ),
        discrete_flows=(
            DiscreteFlow(
                date=(today + timedelta(days=30)).isoformat(),
                amount_cents=cents(1200.00), kind="expense",
                title="Retainer setup equipment", category="Shops",
            ),
        ),
        config_overrides={"label": "Add a $2,000 monthly freelance retainer"},
    )
    studio = ScenarioOverlay(
        added_recurring=(
            RecurringAdd(
                title="Shared creative studio", amount_cents=cents(650.00),
                recurrence="monthly", kind="expense", category="Housing",
                anchor_date=today.isoformat(),
            ),
        ),
        config_overrides={"label": "Add a $650 monthly studio lease"},
    )

    s1 = ScenarioORM(
        user_id=user.id, name="Add freelance retainer",
        overlay_json=json.dumps(overlay_to_json(retainer)),
    )
    s2 = ScenarioORM(
        user_id=user.id, name="Lease a creative studio",
        overlay_json=json.dumps(overlay_to_json(studio)),
    )
    db.add_all([s1, s2])
    db.flush()

    # Baseline is derived from the visible account balances, not a stale constant.
    liquid_net_cents = sum(int(account.balance) for account in accounts.values())
    db.add(PlanOfRecordORM(
        user_id=user.id, scenario_id=s1.id,
        rule_ids_json=json.dumps([]),
        baseline_snapshot_json=json.dumps({
            "as_of": today.isoformat(),
            "net_worth_cents": liquid_net_cents,
            "monthly_savings_cents": cents(750.00),
        }),
        status="active",
    ))


def seed_rules(db, user: UserORM, goals: dict[str, GoalORM]) -> dict[str, RuleORM]:
    """Four engine-valid rules, exercised against actual seeded transactions."""
    notify_rule = RuleORM(
        user_id=user.id, name="Big purchase heads-up", enabled=1,
        conditions=json.dumps([
            {"field": "type", "op": "eq", "value": "expense"},
            {"field": "amount", "op": "gt", "value": 200.00},
        ]),
        action_type="notify", action_params=json.dumps({"message": "Large purchase posted"}),
        priority=10,
    )
    roundup_rule = RuleORM(
        user_id=user.id, name="Round up everyday spending for a home", enabled=1,
        conditions=json.dumps([{"field": "category", "op": "in",
                                "value": ["Food", "Food and Drink", "Shops"]}]),
        action_type="roundup", action_params=json.dumps({"nearest": "1"}),
        target_kind="goal", target_id=goals["House Down Payment"].id, priority=5,
    )
    tax_rule = RuleORM(
        user_id=user.id, name="Set aside 15% of freelance income", enabled=1,
        conditions=json.dumps([
            {"field": "type", "op": "eq", "value": "income"},
            {"field": "source_type", "op": "eq", "value": "self_employment"},
        ]),
        action_type="allocate", action_params=json.dumps({"pct": 15}),
        target_kind="goal", target_id=goals["Tax Reserve"].id, priority=8,
    )
    categorize_rule = RuleORM(
        user_id=user.id, name="Tag Adobe as a tool", enabled=1,
        conditions=json.dumps([{"field": "title", "op": "contains", "value": "Adobe"}]),
        action_type="categorize", action_params=json.dumps({"category": "Service"}),
        priority=1,
    )
    db.add_all([notify_rule, tax_rule, roundup_rule, categorize_rule])
    db.flush()

    # Drive the real engine over a small, inspectable slice of real rows. The
    # execution log and any goal/proposal/notification effects therefore agree
    # with the transaction IDs, conditions, thresholds, and targets.
    engine = RuleEngine(db)
    expenses = db.execute(
        select(ExpenseORM)
        .where(ExpenseORM.user_id == user.id)
        .order_by(ExpenseORM.date.desc(), ExpenseORM.id.desc())
    ).scalars().all()
    selected_expenses: list[ExpenseORM] = []
    for predicate in (
        lambda row: "adobe" in row.title.casefold(),
        lambda row: row.amount > cents(200),
        lambda row: row.category in {"Food", "Food and Drink", "Shops"} and row.amount < cents(200),
    ):
        match = next((row for row in expenses if predicate(row)), None)
        if match is not None and match not in selected_expenses:
            selected_expenses.append(match)
    for row in selected_expenses:
        engine.run_on_transaction(user.id, "expense", row.id, {
            "id": row.id,
            "title": row.title,
            "amount": row.amount / 100,
            "date": row.date,
            "category": row.category,
            "account_id": row.account_id,
            "type": "expense",
        })

    freelance_rows = db.execute(
        select(IncomeORM)
        .where(
            IncomeORM.user_id == user.id,
            IncomeORM.source_type == "self_employment",
        )
        .order_by(IncomeORM.amount.asc())
        .limit(2)
    ).scalars().all()
    for row in freelance_rows:
        engine.run_on_transaction(user.id, "income", row.id, {
            "id": row.id,
            "title": row.title,
            "amount": row.amount / 100,
            "date": row.date,
            "category": row.category,
            "account_id": row.account_id,
            "type": "income",
            "source_type": row.source_type,
        })
    db.flush()
    return {
        "notify": notify_rule,
        "tax": tax_rule,
        "roundup": roundup_rule,
        "categorize": categorize_rule,
    }


def seed_merchant_aliases(db, user: UserORM) -> None:
    """Two reversible aliases grounded in descriptors present in the ledger."""
    for alias, canonical, label in [
        ("AMZN Mktp US*8421", "Amazon", "Amazon"),
        ("UBER *TRIP 9072", "Uber", "Uber"),
    ]:
        db.add(MerchantAliasORM(
            user_id=user.id,
            alias_key=normalize_merchant(alias),
            canonical_key=normalize_merchant(canonical),
            canonical_label=label,
            source="user",
            active=1,
        ))


def seed_misc(
    db, user: UserORM, today: date, goals: dict[str, GoalORM]
) -> None:
    """Learned mappings, durable facts, settings, and exact notifications."""
    # Merchant → category learned mappings.
    for merchant, cat in [
        ("blue bottle coffee", "Food and Drink"),
        ("shell gas", "Transportation"),
        ("steam", "Entertainment"),
        ("whole foods", "Food"),
        ("walgreens", "Health"),
        ("planet fitness", "Fitness"),
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

    db.flush()
    month_prefix = today.strftime("%Y-%m")
    shops_spend = db.execute(
        select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(
            ExpenseORM.user_id == user.id,
            ExpenseORM.category == "Shops",
            ExpenseORM.date.like(f"{month_prefix}%"),
        )
    ).scalar_one()
    shops_limit = db.execute(
        select(BudgetORM.monthly_limit).where(
            BudgetORM.user_id == user.id,
            BudgetORM.category == "Shops",
        )
    ).scalar_one()
    adobe = db.execute(
        select(MerchantLifecycleORM).where(
            MerchantLifecycleORM.user_id == user.id,
            MerchantLifecycleORM.merchant == "adobe creative cloud",
        )
    ).scalar_one()
    hulu = db.execute(
        select(MerchantLifecycleORM).where(
            MerchantLifecycleORM.user_id == user.id,
            MerchantLifecycleORM.merchant == "hulu",
        )
    ).scalar_one()
    hulu_days = (today - date.fromisoformat(hulu.last_date)).days
    laptop = goals["New Laptop"]
    laptop_pct = round(100 * laptop.progress / laptop.amount)

    # Every numeric claim below is derived from rows visible in the demo.
    notices = [
        ("demo_metadata", "Canonical demo dataset", f"Dataset revision {DEMO_DATASET_REVISION}.", DEMO_DATASET_MARKER_REF, 1),
        ("anomaly", "Unusual spend in Travel", "A $342.00 conference flight is above Maya’s usual Travel charge.", "anomaly:Travel:flight", 0),
        (
            "budget_overrun",
            "Shops envelope needs attention",
            f"Shops is ${(shops_spend - shops_limit) / 100:,.2f} over its "
            f"${shops_limit / 100:,.2f} monthly envelope (${shops_spend / 100:,.2f} spent).",
            f"budget_overrun:Shops:{month_prefix}",
            0,
        ),
        (
            "price_creep",
            "Adobe raised its price",
            f"Adobe Creative Cloud moved from ${adobe.prev_amount / 100:,.2f} to "
            f"${adobe.last_amount / 100:,.2f} ({adobe.price_change_pct * 100:.1f}%).",
            "price_creep:adobe",
            0,
        ),
        ("zombie_sub", "Hulu looks dormant", f"The modeled lifecycle state is dormant; the last Hulu charge was {hulu_days} days ago.", "lifecycle:hulu:dormant", 1),
        ("goal", "Laptop goal almost there", f"New Laptop is {laptop_pct}% funded (${laptop.progress / 100:,.2f} of ${laptop.amount / 100:,.2f}).", f"goal:new-laptop:{laptop_pct}", 1),
        ("demo_guide", "Automation is configurable", "Four editable rules show alerts, round-ups, categorization, and a Tax Reserve set-aside. Pausing a rule takes effect immediately.", "demo:rules:guide", 0),
    ]
    for typ, title, msg, ref, read in notices:
        db.add(NotificationORM(
            user_id=user.id, type=typ, title=title, message=msg, ref=ref, read=read,
        ))


def seed_imports(db, user: UserORM, accounts: dict, today: date) -> None:
    """Reconciliation Desk content: a clean statement that ties out, a messy one
    with flagged rows + a discrepancy, and a single scanned receipt — all left in
    ``pending_review`` so the desk isn't empty."""
    checking = accounts["checking"]
    credit = accounts["credit"]
    period = f"{(today - timedelta(days=30)).isoformat()} to {today.isoformat()}"

    def _add_rows(session_id: int, opening: int, specs: list) -> int:
        """specs: (title, dollars_signed, category, status, reason, match_ref).
        Adds ImportRows with a cumulative running balance; returns final running."""
        running = opening
        for i, (title, amt, cat, status, reason, mref) in enumerate(specs):
            c = cents(amt)
            running += c
            db.add(ImportRowORM(
                session_id=session_id, user_id=user.id, title=title, amount=c,
                date=(today - timedelta(days=26 - i)).isoformat(), category=cat,
                merchant_key=title.lower(), running_balance=running, status=status,
                reason=reason, included=(0 if status == "exception" else 1),
                match_ref=mref,
            ))
        return running

    # 1) Clean statement — every row OK, balances reconcile.
    clean = ImportSessionORM(
        user_id=user.id, account_id=checking.id, source_kind="pdf",
        status="pending_review", opening_balance=cents(5200.00),
        statement_period=period, reconciled=1, discrepancy_cents=0,
    )
    db.add(clean)
    db.flush()
    end = _add_rows(clean.id, cents(5200.00), [
        ("Whole Foods", -92.15, "Food", "ok", None, None),
        ("Acme Corp Payroll", 2650.00, "Work", "ok", None, None),
        ("Shell Gas", -51.30, "Transportation", "ok", None, None),
        ("Amazon", -124.99, "Shops", "ok", None, None),
        ("Trader Joe's", -63.40, "Food", "ok", None, None),
        ("Comcast Internet", -79.99, "Utilities", "ok", None, None),
        ("Chipotle", -14.09, "Food and Drink", "ok", None, None),
        ("Uber", -18.50, "Transportation", "ok", None, None),
    ])
    clean.closing_balance = end  # ties out exactly

    # 2) Messy statement — a duplicate, a transfer, a needs-category, an unreadable
    #    exception, and a $23.45 discrepancy so the balance check fails.
    messy = ImportSessionORM(
        user_id=user.id, account_id=checking.id, source_kind="image",
        status="pending_review", opening_balance=cents(3000.00),
        statement_period=period, reconciled=0, discrepancy_cents=-cents(23.45),
    )
    db.add(messy)
    db.flush()
    end2 = _add_rows(messy.id, cents(3000.00), [
        ("Costco", -210.45, "Shops", "ok", None, None),
        ("Venmo — Jordan", -45.00, "Other", "needs_category", "missing_category", None),
        ("Amazon", -49.99, "Shops", "duplicate", "possible_duplicate", 1),
        ("Transfer to Savings", -1000.00, "Transfer", "transfer_candidate", "looks_like_transfer", None),
        ("SQ *UNREADABLE", 0.00, "Other", "exception", "amount_unreadable", None),
        ("Spotify", -11.99, "Entertainment", "ok", None, None),
    ])
    messy.closing_balance = end2 - cents(23.45)  # off by the missed charge

    # 3) A single scanned receipt as a one-row import.
    receipt = ImportSessionORM(
        user_id=user.id, account_id=credit.id, source_kind="image",
        status="pending_review", reconciled=0, discrepancy_cents=0,
    )
    db.add(receipt)
    db.flush()
    db.add(ImportRowORM(
        session_id=receipt.id, user_id=user.id, title="Trader Joe's",
        amount=-cents(62.43), date=(today - timedelta(days=2)).isoformat(),
        category="Food", merchant_key="trader joe's", status="ok", included=1,
    ))


def seed_detangle(db, user: UserORM, accounts: dict, today: date) -> None:
    """A real transfer pair and refund pair the Detangle pass can match, plus the
    notifications that pass would raise (so the insight shows immediately)."""
    checking, savings, credit = accounts["checking"], accounts["savings"], accounts["credit"]
    db.add_all([
        # transfer: leaves checking, lands in savings, same amount/day
        ExpenseORM(user_id=user.id, title="Transfer to Savings", amount=cents(1200.00),
                   date=(today - timedelta(days=9)).isoformat(), category="Transfer",
                   account_id=checking.id),
        IncomeORM(user_id=user.id, title="Transfer from Checking", amount=cents(1200.00),
                  date=(today - timedelta(days=9)).isoformat(), category="Transfer",
                  source_type="other", account_id=savings.id),
        # refund: an Amazon charge then an equal credit a few days later
        ExpenseORM(user_id=user.id, title="Amazon", amount=cents(79.99),
                   date=(today - timedelta(days=16)).isoformat(), category="Shops",
                   account_id=credit.id),
        IncomeORM(user_id=user.id, title="Amazon refund", amount=cents(79.99),
                  date=(today - timedelta(days=11)).isoformat(), category="Shops",
                  source_type="other", account_id=credit.id),
    ])
    db.add(NotificationORM(
        user_id=user.id, type="detangle", title="Possible transfer",
        message="“Transfer to Savings” and “Transfer from Checking” look like a "
                "transfer between your own accounts — not new spending.",
        ref="detangle:transfer:checking-savings", read=0,
    ))
    db.add(NotificationORM(
        user_id=user.id, type="detangle", title="Possible refund",
        message="A $79.99 credit “Amazon refund” looks like a refund of an earlier "
                "“Amazon” charge. Net it out so it doesn't read as income.",
        ref="detangle:refund:amazon", read=0,
    ))


def seed_current_month_extras(db, user: UserORM, accounts: dict, today: date) -> None:
    """Push ONE envelope over budget this month so Budget Status shows the red
    over-budget state next to the on-pace ones (Shops limit is $360)."""
    db.add(ExpenseORM(
        user_id=user.id, title="Best Buy — monitor", amount=cents(420.00),
        date=(today - timedelta(days=2)).isoformat(), category="Shops",
        account_id=accounts["credit"].id,
    ))
    # Raw bank descriptors paired with the canonical merchants used by the
    # reversible alias sidecar.
    db.add_all([
        ExpenseORM(
            user_id=user.id, title="AMZN Mktp US*8421", amount=cents(38.71),
            date=(today - timedelta(days=5)).isoformat(), category="Shops",
            account_id=accounts["credit"].id,
        ),
        ExpenseORM(
            user_id=user.id, title="UBER *TRIP 9072", amount=cents(18.42),
            date=(today - timedelta(days=4)).isoformat(), category="Transportation",
            account_id=accounts["checking"].id,
        ),
    ])


# ---------------------------------------------------------------------------
# Optional legacy game helpers
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
# Verification + orchestration
# ---------------------------------------------------------------------------


def verify_demo_seed(db, user: UserORM) -> None:
    """Raise when the canonical showcase contradicts its public contract."""
    db.flush()
    failures: list[str] = []
    readiness = assess_demo_readiness(db, enabled=True)
    if not readiness.ready:
        failures.append(f"readiness={readiness.reason_code}")
    if user.full_name != "Maya Chen" or user.game_mode != "off":
        failures.append("persona/game-mode mismatch")

    mortgage_docs = db.execute(
        select(func.count(TaxDocumentORM.id)).where(
            TaxDocumentORM.user_id == user.id,
            TaxDocumentORM.form_type == "1098",
        )
    ).scalar_one()
    if mortgage_docs:
        failures.append("renter persona has a mortgage 1098")

    rules = db.execute(select(RuleORM).where(RuleORM.user_id == user.id)).scalars().all()
    execution_counts = dict(db.execute(
        select(RuleExecutionORM.rule_id, func.count(RuleExecutionORM.id))
        .where(RuleExecutionORM.user_id == user.id)
        .group_by(RuleExecutionORM.rule_id)
    ).all())
    for rule in rules:
        if execution_counts.get(rule.id, 0) < 1:
            failures.append(f"rule has no real execution: {rule.name}")

    observed = {
        normalize_merchant(title)
        for title in db.execute(
            select(ExpenseORM.title).where(ExpenseORM.user_id == user.id)
        ).scalars()
    }
    aliases = db.execute(
        select(MerchantAliasORM).where(MerchantAliasORM.user_id == user.id)
    ).scalars().all()
    if any(a.alias_key not in observed or a.canonical_key not in observed for a in aliases):
        failures.append("merchant alias is not grounded in observed descriptors")

    adobe = db.execute(
        select(MerchantLifecycleORM).where(
            MerchantLifecycleORM.user_id == user.id,
            MerchantLifecycleORM.merchant == "adobe creative cloud",
        )
    ).scalar_one_or_none()
    if adobe is None or price_creep_pct(adobe.last_amount, adobe.prev_amount) != adobe.price_change_pct:
        failures.append("Adobe lifecycle price change is inconsistent")

    visible_total = db.execute(
        select(func.sum(AccountORM.balance)).where(AccountORM.user_id == user.id)
    ).scalar_one()
    latest_snapshot = db.execute(
        select(BalanceSnapshotORM)
        .where(BalanceSnapshotORM.user_id == user.id)
        .order_by(BalanceSnapshotORM.date.desc(), BalanceSnapshotORM.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_snapshot is None or int(latest_snapshot.total) != int(visible_total):
        failures.append("latest net-worth snapshot does not reconcile to accounts")

    projected = RecurringService(db).project_expenses(
        user.id, date.today(), date.today() + timedelta(days=62)
    )
    if any(row["title"] == "Hulu" for row in projected):
        failures.append("dormant Hulu is still projected as an active recurring bill")

    if failures:
        raise RuntimeError("demo seed verification failed: " + "; ".join(failures))


def main(*, reset_financials: bool = False, bootstrap: bool = False) -> None:
    db = SessionLocal()
    try:
        auth = AuthService()
        user = db.execute(
            select(UserORM).where(UserORM.username == DEMO["username"])
        ).scalar_one_or_none()

        if user is not None and bootstrap:
            readiness = assess_demo_readiness(db, enabled=True)
            if readiness.ready:
                logger.info("demo bootstrap: canonical seed is already ready; no changes")
                return
            raise SystemExit(
                "Demo user exists but is incomplete. Bootstrap will not reset an "
                "existing database. Point the demo service at a fresh database, or "
                "run explicitly with --reset-financials after reviewing the runbook."
            )

        if user is None:
            auth.create_user(db, NewUser(**DEMO))
            db.flush()
            user = db.execute(
                select(UserORM).where(UserORM.username == DEMO["username"])
            ).scalar_one()
            if settings.enable_rls:
                set_tenant(db, user.id)
            logger.info("created user '%s'", DEMO["username"])
        elif reset_financials:
            if settings.enable_rls:
                set_tenant(db, user.id)
            reset_user(db, user.id)
            logger.info("reset existing user '%s' (financial rows)", DEMO["username"])
        else:
            raise SystemExit(
                "Demo user already exists; refusing an implicit destructive reset. "
                "Use --bootstrap for deployment or --reset-financials explicitly."
            )

        today = date.today()
        RNG.seed(20260619)  # deterministic even across two runs in one process
        start = today - timedelta(days=365)  # ~12 months of income history
        exp_start = today - timedelta(days=185)  # ~6 months of spending

        # --- Part B: financial / showcase domains --------------------------
        seed_user_config(user)
        accounts = seed_accounts(db, user)
        n_inc = seed_income(db, user, accounts, start, today)
        n_exp, tax_refs = seed_expenses(db, user, accounts, exp_start, today)
        seed_budgets(db, user)
        goals = seed_goals_and_earmarks(db, user, today)
        account_total_cents = sum(int(account.balance) for account in accounts.values())
        seed_balance_snapshots(db, user, exp_start, today, account_total_cents)
        seed_liabilities(db, user, accounts)
        db.flush()  # lifecycle facts are derived from these actual transactions
        seed_merchant_lifecycle(db, user, today)
        seed_tax(db, user, tax_refs, today)
        seed_scenarios(db, user, accounts, today)
        seed_imports(db, user, accounts, today)
        seed_detangle(db, user, accounts, today)
        seed_current_month_extras(db, user, accounts, today)
        db.flush()
        seed_merchant_aliases(db, user)
        seed_rules(db, user, goals)
        seed_misc(db, user, today, goals)
        verify_demo_seed(db, user)
        db.commit()
        logger.info(
            "seeded financials: 3 accounts, %d expenses, %d income, goals/budgets/"
            "liabilities/tax/scenarios/rules/notifications", n_exp, n_inc,
        )

        logger.info("done. login →  username: demo   password: Demo123!")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the demo showcase account.")
    parser.add_argument(
        "--bootstrap", action="store_true",
        help="Seed only when the demo user is absent; otherwise verify/no-op or fail.",
    )
    parser.add_argument(
        "--reset-financials", action="store_true",
        help="Explicitly replace the existing demo user's financial showcase rows.",
    )
    args = parser.parse_args()
    main(reset_financials=args.reset_financials, bootstrap=args.bootstrap)
