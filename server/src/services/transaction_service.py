"""Shared service for creating, reading, updating, and deleting income and expenses.

Holds the create, update, and delete logic (plus the balance adjustment) that
used to be copied between ``routers/income.py`` and ``routers/expenses.py``. The
``balance_sign`` parameter sets which way a balance moves:

    +1  for income   (creating one adds to the account balance)
    -1  for expense  (creating one subtracts from the account balance)

Money is stored as integer cents in the DB. This service takes dollar floats in
(from the Pydantic request schemas) and gives dollar floats back, converting at
the boundary with ``dollars_to_cents`` and ``cents_to_dollars``.
"""

from datetime import date
from typing import Any, Literal, Type, Union

from fastapi import HTTPException
from sqlalchemy import select, func, update, delete
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    TaxTag as TaxTagORM,
)
from server.src.money import dollars_to_cents, cents_to_dollars
from server.src.services.categorization_service import (
    CategorizationService,
    canonicalize_category,
)
from server.src.services.rule_engine import RuleEngine
from server.src.services.recurring_service import latest_recurring_rows

# Type alias for the two ORM model classes this service handles.
TransactionModel = Type[ExpenseORM] | Type[IncomeORM]


class TransactionService:
    """Income and expense transactions, backed by the ORM."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Helpers ───────────────────────────────────────────────────────────

    def _adjust_balance(self, account_id: int, delta_cents: int) -> None:
        """Apply *delta_cents* to an account's balance with an issued SQL UPDATE.

        This is a server-side ``balance = balance + delta`` (not a stale
        read-modify-write on a loaded ORM object), so two concurrent adjustments
        against the same account can't lose each other's update. The expired
        attribute is refreshed lazily by the ORM the next time it is read.
        """
        if delta_cents == 0:
            # Still bump last_updated so the row reflects the touch, but skip the
            # arithmetic no-op.
            self.db.execute(
                update(AccountORM)
                .where(AccountORM.id == account_id)
                .values(
                    last_updated=func.current_timestamp(),
                    plaid_balance_refreshed_at=None,
                )
            )
            return
        self.db.execute(
            update(AccountORM)
            .where(AccountORM.id == account_id)
            .values(
                balance=AccountORM.balance + delta_cents,
                last_updated=func.current_timestamp(),
                plaid_balance_refreshed_at=None,
            )
        )

    def _own_account(self, account_id: int, user_id: int) -> AccountORM:
        """Return the account if it belongs to *user_id*, else 404."""
        account = self.db.execute(
            select(AccountORM).where(
                AccountORM.id == account_id,
                AccountORM.user_id == user_id,
            )
        ).scalar_one_or_none()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return account

    def _own_transaction(
        self,
        tx_id: int,
        user_id: int,
        model: TransactionModel,
    ):
        """Return the transaction row if owned by *user_id* (via account), else 404."""
        row = self.db.execute(
            select(model)
            .join(AccountORM, model.account_id == AccountORM.id)
            .where(model.id == tx_id, AccountORM.user_id == user_id)
        ).scalar_one_or_none()
        if row is None:
            label = "Expense" if model is ExpenseORM else "Income"
            raise HTTPException(status_code=404, detail=f"{label} not found")
        return row

    @staticmethod
    def _row_to_dict(row, tx_type: str | None = None) -> dict[str, Any]:
        """Serialize an ORM transaction row to a dict with dollar amounts."""
        d: dict[str, Any] = {
            "id": row.id,
            "title": row.title,
            "amount": cents_to_dollars(row.amount),
            "date": row.date,
            "category": row.category,
            "account_id": row.account_id,
        }
        if tx_type is not None:
            d["type"] = tx_type
        # Include recurrence for expenses (may be None).
        if hasattr(row, "recurrence"):
            d["recurrence"] = row.recurrence
        return d

    # ── Public API ────────────────────────────────────────────────────────

    def list_all(
        self,
        user_id: int,
        model: TransactionModel,
    ) -> list[dict[str, Any]]:
        """Return every transaction of *model* type owned by *user_id*."""
        account_ids = (
            self.db.execute(
                select(AccountORM.id).where(AccountORM.user_id == user_id)
            )
            .scalars()
            .all()
        )
        if not account_ids:
            return []

        rows = (
            self.db.execute(
                select(model).where(model.account_id.in_(account_ids))
            )
            .scalars()
            .all()
        )
        tx_type = "expense" if model is ExpenseORM else "income"
        return [self._row_to_dict(r, tx_type) for r in rows]

    def get_one(
        self,
        tx_id: int,
        user_id: int,
        model: TransactionModel,
    ) -> dict[str, Any]:
        """Return a single transaction dict, or 404."""
        row = self._own_transaction(tx_id, user_id, model)
        tx_type = "expense" if model is ExpenseORM else "income"
        return self._row_to_dict(row, tx_type)

    def create(
        self,
        user_id: int,
        model: TransactionModel,
        balance_sign: Literal[1, -1],
        *,
        title: str,
        amount: float,
        tx_date: Union[str, date],
        category: str,
        account_id: int,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Insert a transaction and adjust the account balance.

        ``balance_sign=+1`` → income (adds to balance).
        ``balance_sign=-1`` → expense (subtracts from balance).
        """
        account = self._own_account(account_id, user_id)
        amount_cents = dollars_to_cents(amount)

        # Normalize a provided label onto the canonical taxonomy so it lines up
        # with budgets and the UI palette. A blank category is left blank here so
        # the expense auto-categorize path below can resolve it.
        if (category or "").strip():
            category = canonicalize_category(category)

        # Pick a category for hand entered expenses: if the user left
        # the category blank, work it out (learned mapping, then rule, then
        # "Other"); if they chose one, remember it so the same merchant sticks.
        if model is ExpenseORM:
            categorizer = CategorizationService(self.db)
            if not (category or "").strip():
                category = categorizer.categorize(user_id, title)[0]
            else:
                categorizer.learn(user_id, title, category, source="user")

        row = model(
            title=title,
            amount=amount_cents,
            date=str(tx_date),
            category=category,
            account_id=account_id,
            user_id=user_id,  # WS2: denormalized tenant key (also backfilled on insert)
        )
        # Set extra columns (e.g. recurrence on Expense).
        if extra_fields:
            for k, v in extra_fields.items():
                setattr(row, k, v)

        self.db.add(row)

        # Issued atomic UPDATE (not account.balance += …) so concurrent
        # adjustments to the same account can't lose each other's write.
        self._adjust_balance(account_id, balance_sign * amount_cents)
        # The in-memory ORM copy is now stale; drop it so any later read of this
        # account reflects the server-side value.
        self.db.expire(account)
        self.db.flush()  # row now has an id — the rules engine needs it

        # v1 Layer B hook: the single creation path runs the rules engine.
        # Plaid imports reuse this same engine later, protected by the same
        # idempotency log. A rules failure never breaks creation.
        tx_type = "expense" if model is ExpenseORM else "income"
        tx_view: dict[str, Any] = {
            "id": row.id,
            "title": row.title,
            "amount": cents_to_dollars(row.amount),
            "date": row.date,
            "category": row.category,
            "account_id": row.account_id,
            "type": tx_type,
        }
        # W5: expose the income's tax/earnings character so a Tax-Reserve allocate
        # rule (condition source_type == self_employment) can match. Absent on
        # expenses, so the income+source_type guard still can't fire on a spend.
        if model is IncomeORM:
            tx_view["source_type"] = getattr(row, "source_type", None)
        RuleEngine(self.db).run_on_transaction(user_id, tx_type, row.id, tx_view)

        label = "Expense" if model is ExpenseORM else "Income"
        return {"message": f"{label} created successfully"}

    def update(
        self,
        tx_id: int,
        user_id: int,
        model: TransactionModel,
        balance_sign: Literal[1, -1],
        *,
        title: str,
        amount: float,
        tx_date: Union[str, date],
        category: str,
        account_id: int,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Update a transaction, adjusting balances for amount and/or account changes."""
        row = self._own_transaction(tx_id, user_id, model)
        old_amount_cents = row.amount
        old_account_id = row.account_id
        new_amount_cents = dollars_to_cents(amount)

        # Keep stored categories on the canonical taxonomy (matches budgets/UI).
        if (category or "").strip():
            category = canonicalize_category(category)

        # If changing accounts, verify ownership of the new account.
        if old_account_id != account_id:
            new_account = self._own_account(account_id, user_id)
            old_account = self._own_account(old_account_id, user_id)

            # Reverse the old transaction's effect on the old account, then apply
            # the new amount to the new account — each via an issued atomic
            # UPDATE so the legs can't lose a concurrent write.
            self._adjust_balance(old_account_id, -balance_sign * old_amount_cents)
            self._adjust_balance(account_id, balance_sign * new_amount_cents)
            self.db.expire(old_account)
            self.db.expire(new_account)
        else:
            # Same account, so just adjust by the difference.
            account = self._own_account(account_id, user_id)
            self._adjust_balance(
                account_id, balance_sign * (new_amount_cents - old_amount_cents)
            )
            self.db.expire(account)

        # Update the transaction row itself.
        row.title = title
        row.amount = new_amount_cents
        row.date = str(tx_date)
        row.category = category
        row.account_id = account_id
        if extra_fields:
            for k, v in extra_fields.items():
                setattr(row, k, v)

        # Remember a user's (re)categorization so future transactions for the
        # same merchant inherit it.
        if model is ExpenseORM and (category or "").strip():
            CategorizationService(self.db).learn(
                user_id, title, category, source="user"
            )

        self.db.flush()

        label = "Expense" if model is ExpenseORM else "Income"
        return {"message": f"{label} updated successfully"}

    def delete(
        self,
        tx_id: int,
        user_id: int,
        model: TransactionModel,
        balance_sign: Literal[1, -1],
    ) -> dict[str, str]:
        """Delete a transaction and reverse its balance effect."""
        row = self._own_transaction(tx_id, user_id, model)
        account = self._own_account(row.account_id, user_id)
        account_id = row.account_id
        row_amount = row.amount

        # Delete the row first, then reverse its balance effect. Both run inside
        # the caller's transaction, but ordering the delete ahead of the balance
        # adjustment means a failure on the delete aborts before the balance is
        # touched — the account can never be left adjusted for a row that still
        # exists. The adjustment itself is an issued atomic UPDATE
        # (``balance = balance + delta``), not a stale read-modify-write.
        # Reverse: income was +, so delete is -.  Expense was -, so delete is +.
        self.db.delete(row)
        self.db.flush()

        # Pillar 3 orphan-integrity guard: a TaxTag references the transaction by
        # ``(tx_type, tx_id)`` WITHOUT an FK (the expense/income id spaces overlap,
        # so it mirrors ``RuleExecution``). No FK ⇒ no cascade, and with
        # autoincrement id reuse a stale tag could later mis-attribute to a
        # different transaction. So we drop the matching tag here, on the single
        # delete path. (The summary engine also INNER-joins as a second guard.)
        tx_type = "expense" if model is ExpenseORM else "income"
        self.db.execute(
            delete(TaxTagORM).where(
                TaxTagORM.tx_type == tx_type,
                TaxTagORM.tx_id == tx_id,
                TaxTagORM.user_id == user_id,
            )
        )

        self._adjust_balance(account_id, -balance_sign * row_amount)
        self.db.expire(account)
        self.db.flush()

        label = "Expense" if model is ExpenseORM else "Income"
        return {"message": f"{label} deleted successfully"}

    def fixed_per_month(self, user_id: int) -> float:
        """Monthlyized current recurring expenses, returned as dollars.

        One latest row represents each merchant/account series, even when the
        ledger retains older occurrences at an old price or cadence.
        """
        account_ids = (
            self.db.execute(
                select(AccountORM.id).where(AccountORM.user_id == user_id)
            )
            .scalars()
            .all()
        )
        if not account_ids:
            return 0.0

        rows = self.db.execute(
            select(ExpenseORM).where(
                ExpenseORM.account_id.in_(account_ids),
                ExpenseORM.recurrence.isnot(None),
            )
        ).scalars().all()
        total_cents = 0
        from server.src.services.recurring_service import RECURRENCE_TO_DAYS

        for row in latest_recurring_rows(rows):
            days = RECURRENCE_TO_DAYS.get(row.recurrence, 30)
            total_cents += (int(row.amount) * 30) // days
        return cents_to_dollars(total_cents) if total_cents else 0.0
