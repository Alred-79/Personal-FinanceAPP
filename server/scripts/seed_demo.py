"""Seed the dev database with a demo user + realistic mock data.

Run:  ./.venv/bin/python -m server.scripts.seed_demo

Creates (or resets) a single demo account so the UI has something to render:
accounts, ~4 months of categorized transactions incl. recurring bills, a
bi-weekly "Work" paycheck (the Safe-to-Spend / budget logic keys off it), and a
couple of savings goals. All money is integer cents; dates are ISO strings.

Idempotent: wipes the demo user's rows and reseeds, so it's safe to re-run.
Login afterward with  username: demo   password: Demo123!
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from server.src.db.session import SessionLocal
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    User as UserORM,
)
from server.src.models import NewUser
from server.src.services.auth_service import AuthService

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


def reset_user(db, user_id: int) -> None:
    for model in (ExpenseORM, IncomeORM, GoalORM, AccountORM):
        db.execute(delete(model).where(model.user_id == user_id))


def main() -> None:
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
            print(f"created user '{DEMO['username']}'")
        else:
            reset_user(db, user.id)
            print(f"reset existing user '{DEMO['username']}'")

        # Give the saver a realistic profile.
        user.savings_percent = 15
        user.spend_warning = 1

        # --- Accounts -------------------------------------------------------
        checking = AccountORM(
            name="Everyday Checking", type="checking",
            balance=cents(3420.55), user_id=user.id, last_updated=datetime.now(),
        )
        savings = AccountORM(
            name="High-Yield Savings", type="savings",
            balance=cents(11250.00), user_id=user.id, last_updated=datetime.now(),
        )
        credit = AccountORM(
            name="Sapphire Credit Card", type="credit",
            balance=cents(-842.13), user_id=user.id, last_updated=datetime.now(),
        )
        db.add_all([checking, savings, credit])
        db.flush()

        today = date.today()
        start = today - timedelta(days=120)  # ~4 months of history

        n_exp = 0
        n_inc = 0

        # --- Bi-weekly paycheck (category "Work" drives the budget engine) ---
        pay_day = start
        while pay_day <= today:
            db.add(IncomeORM(
                title="Acme Corp Payroll", amount=cents(2650.00),
                date=pay_day.isoformat(), category="Work", recurrence="bi-weekly",
                source_type="employment", account_id=checking.id, user_id=user.id,
            ))
            n_inc += 1
            pay_day += timedelta(days=14)

        # Occasional freelance income
        for _ in range(3):
            d = start + timedelta(days=RNG.randint(5, 115))
            db.add(IncomeORM(
                title="Freelance — design gig", amount=cents(RNG.randint(350, 900)),
                date=d.isoformat(), category="Work", source_type="freelance",
                account_id=checking.id, user_id=user.id,
            ))
            n_inc += 1

        # --- Monthly recurring bills ----------------------------------------
        cursor = date(start.year, start.month, 1)
        while cursor <= today:
            for title, cat, amt, dom in MONTHLY_BILLS:
                try:
                    bill_date = cursor.replace(day=dom)
                except ValueError:
                    continue
                if start <= bill_date <= today:
                    db.add(ExpenseORM(
                        title=title, amount=cents(amt), date=bill_date.isoformat(),
                        category=cat, recurrence="monthly",
                        account_id=checking.id, user_id=user.id,
                    ))
                    n_exp += 1
            # advance one month
            cursor = (cursor.replace(day=28) + timedelta(days=7)).replace(day=1)

        # --- Discretionary spend: a few transactions per week ---------------
        day = start
        while day <= today:
            for _ in range(RNG.randint(0, 3)):
                title, cat, lo, hi = RNG.choice(DISCRETIONARY)
                amt = RNG.uniform(lo, hi)
                acct = credit if RNG.random() < 0.6 else checking
                db.add(ExpenseORM(
                    title=title, amount=cents(amt), date=day.isoformat(),
                    category=cat, account_id=acct.id, user_id=user.id,
                ))
                n_exp += 1
            day += timedelta(days=1)

        # --- Goals ----------------------------------------------------------
        db.add_all([
            GoalORM(
                name="Emergency Fund", description="6 months of essentials",
                amount=cents(15000.00), progress=cents(11250.00),
                date=(today + timedelta(days=210)).isoformat(),
                completed=0, user_id=user.id,
            ),
            GoalORM(
                name="Japan Trip", description="Two weeks, spring",
                amount=cents(6000.00), progress=cents(1850.00),
                date=(today + timedelta(days=300)).isoformat(),
                completed=0, user_id=user.id,
            ),
            GoalORM(
                name="New Laptop", description="M-series upgrade",
                amount=cents(2200.00), progress=cents(2200.00),
                date=(today - timedelta(days=10)).isoformat(),
                completed=1, user_id=user.id,
            ),
        ])

        db.commit()
        print(f"seeded: 3 accounts, {n_exp} expenses, {n_inc} income, 3 goals")
        print("login →  username: demo   password: Demo123!")
    finally:
        db.close()


if __name__ == "__main__":
    main()
