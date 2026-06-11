"""Plaid integration service. Built on the ORM, syncs with a cursor.

Takes a ``Session`` in ``__init__`` instead of the old ``BaseDatabridge``
singleton.

Sign convention (Plaid to Finance-Tracker):
    Plaid ``amount > 0``  → Expense (money leaving the account)
    Plaid ``amount < 0``  → Income  (money entering the account)
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.databridge.plaid_client import PlaidClient
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Token as TokenORM,
)
from server.src.money import dollars_to_cents
from server.src.models import UserInDB
from server.src.services.categorization_service import (
    CategorizationService,
    canonicalize_category,
)

logger = logging.getLogger(__name__)

# Merchant names from Plaid can carry long reference codes / store metadata.
# Cap what we store so a pathological description can't bloat a row or the UI.
_MAX_TITLE_LEN = 200


def _clean_title(name: object) -> str:
    """Trim and length-cap a raw Plaid transaction name before storing it."""
    return str(name or "").strip()[:_MAX_TITLE_LEN]


def _extract_category(txn: dict) -> str:
    """A best effort, canonicalized category for a Plaid transaction dict.

    Prefers ``personal_finance_category.primary`` (the newer field), falling
    back to the legacy ``category`` list. Plaid's machine codes (e.g.
    ``FOOD_AND_DRINK``) are mapped onto the app's canonical labels via
    ``canonicalize_category`` so imports line up with budgets and the UI palette.
    """
    pfc = txn.get("personal_finance_category")
    if pfc and isinstance(pfc, dict) and pfc.get("primary"):
        return canonicalize_category(pfc["primary"])

    cats = txn.get("category")
    if cats and len(cats) > 0:
        return canonicalize_category(cats[0])

    return "Other"


def _is_usd(txn: dict) -> bool:
    """Whether a Plaid transaction is denominated in USD.

    The app is USD-only: balances carry no currency and the MCP context labels
    every figure "USD".  Importing a EUR/GBP/crypto transaction would silently
    mislabel and (worse) sum it as if it were dollars.  A ``None``
    ``iso_currency_code`` is treated as USD (Plaid omits it for some feeds);
    any non-USD ISO code, or a set ``unofficial_currency_code`` (e.g. crypto),
    is rejected.
    """
    iso = txn.get("iso_currency_code")
    if iso is not None and iso != "USD":
        return False
    if txn.get("unofficial_currency_code"):
        return False
    return True


class PlaidService:
    def __init__(self, db: Session):
        self.plaid = PlaidClient()
        self.db = db

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def get_balance(self, account_id: int, current_user: UserInDB):
        token = self.db.execute(
            select(TokenORM).where(
                TokenORM.user_id == current_user.id, TokenORM.id == account_id
            )
        ).scalar_one_or_none()
        # Unknown / unowned token id is a 404 at the router, not a 500.
        if token is None:
            return None
        accounts = self.plaid.get_balance(token.key)  # type: ignore[arg-type]
        if not accounts:
            return None
        return accounts[0].to_dict()

    # ------------------------------------------------------------------
    # Sync driven by a cursor
    # ------------------------------------------------------------------

    def _resolve_account_for_token(self, token: TokenORM) -> Optional[int]:
        """Return the local ``accounts.id`` that matches this token.

        The current schema links Token ↔ Account by sharing the same
        ``name`` under the same user.
        """
        row = self.db.execute(
            select(AccountORM.id).where(
                AccountORM.user_id == token.user_id,
                AccountORM.name == token.name,
            )
        ).scalar_one_or_none()
        return row

    def sync_token(self, token: TokenORM) -> dict:
        """Run a sync (driven by a cursor) for a single Plaid token or item.

        Returns a summary dict ``{"added": N, "modified": N, "removed": N}``.
        """
        account_id = self._resolve_account_for_token(token)
        if account_id is None:
            logger.warning(
                "No local account found for token %s (%s); skipping sync.",
                token.id,
                token.name,
            )
            return {"added": 0, "modified": 0, "removed": 0}

        result = self.plaid.sync_transactions(
            token.key, token.cursor or ""  # type: ignore[arg-type]
        )

        added = self._process_added(result.added, account_id, token.user_id)
        modified = self._process_modified(result.modified, account_id)
        removed = self._process_removed(result.removed, account_id)

        # Persist the cursor so the next sync is incremental.
        token.cursor = result.next_cursor

        return {"added": added, "modified": modified, "removed": removed}

    def sync_all_tokens(self, current_user: UserInDB) -> list[dict]:
        """Sync every Plaid token or item owned by *current_user*.

        Returns one summary dict per token.
        """
        tokens = (
            self.db.execute(
                select(TokenORM).where(TokenORM.user_id == current_user.id)
            )
            .scalars()
            .all()
        )

        summaries = []
        for token in tokens:
            summary = self.sync_token(token)
            summaries.append({"token": token.name, **summary})

        return summaries

    # ── Helpers ────────────────────────────────────────────────────────

    def _process_added(
        self, transactions: list[dict], account_id: int, user_id: int | None = None
    ) -> int:
        """Insert new transactions, deduplicating on ``plaid_transaction_id``.

        When *user_id* is given, expenses are categorized through the
        categorizer (a user's learned rename first, then built-in keyword rules),
        falling back to Plaid's own category — canonicalized to the app's
        taxonomy — so a manual rename keeps sticking on later syncs. Without a
        *user_id* the canonicalized Plaid category is used as-is.
        """
        categorizer = (
            CategorizationService(self.db) if user_id is not None else None
        )
        count = 0
        for txn in transactions:
            if not _is_usd(txn):
                logger.warning(
                    "Skipping non-USD Plaid transaction %s (currency=%s)",
                    txn.get("transaction_id"),
                    txn.get("iso_currency_code") or txn.get("unofficial_currency_code"),
                )
                continue
            plaid_txn_id = txn["transaction_id"]
            category = _extract_category(txn)
            amount = txn["amount"]

            # A zero-dollar transaction carries no financial meaning and the
            # expense/income sign is undefined for it, so don't import a bogus
            # $0 row (the convention is amount > 0 → expense, < 0 → income).
            if amount == 0:
                continue

            if amount > 0:
                # Expense (money leaving account). Resolve the category through
                # the categorizer so a user's learned rename and the built-in
                # keyword rules win over Plaid's guess, with the canonicalized
                # Plaid category as the fallback default.
                if categorizer is not None:
                    assert user_id is not None
                    category = categorizer.categorize(
                        user_id, txn["name"], default=category, use_llm=False
                    )[0]
                existing = self.db.execute(
                    select(ExpenseORM.id).where(
                        ExpenseORM.account_id == account_id,
                        ExpenseORM.plaid_transaction_id == plaid_txn_id,
                    )
                ).scalar_one_or_none()
                if not existing:
                    self.db.add(
                        ExpenseORM(
                            title=_clean_title(txn["name"]),
                            amount=dollars_to_cents(float(amount)),
                            date=str(txn["date"]),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    )
                    count += 1
            else:
                # Income (money entering account)
                existing = self.db.execute(
                    select(IncomeORM.id).where(
                        IncomeORM.account_id == account_id,
                        IncomeORM.plaid_transaction_id == plaid_txn_id,
                    )
                ).scalar_one_or_none()
                if not existing:
                    self.db.add(
                        IncomeORM(
                            title=_clean_title(txn["name"]),
                            amount=dollars_to_cents(-float(amount)),
                            date=str(txn["date"]),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    )
                    count += 1

        return count

    def _process_modified(self, transactions: list[dict], account_id: int) -> int:
        """Update existing transactions by ``plaid_transaction_id``."""
        count = 0
        for txn in transactions:
            if not _is_usd(txn):
                logger.warning(
                    "Skipping non-USD Plaid transaction %s (currency=%s)",
                    txn.get("transaction_id"),
                    txn.get("iso_currency_code") or txn.get("unofficial_currency_code"),
                )
                continue
            plaid_txn_id = txn["transaction_id"]
            category = _extract_category(txn)
            amount = txn["amount"]

            # Try to find in expenses first, then income
            expense = self.db.execute(
                select(ExpenseORM).where(
                    ExpenseORM.account_id == account_id,
                    ExpenseORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()

            income = self.db.execute(
                select(IncomeORM).where(
                    IncomeORM.account_id == account_id,
                    IncomeORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()

            if amount >= 0:
                # Should be an expense
                if income:
                    # Sign flipped: it was income, now it's an expense. Delete the old one, create a new one.
                    self.db.delete(income)
                    self.db.add(
                        ExpenseORM(
                            title=_clean_title(txn["name"]),
                            amount=dollars_to_cents(float(amount)),
                            date=str(txn["date"]),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    )
                    count += 1
                elif expense:
                    expense.title = _clean_title(txn["name"])
                    expense.amount = dollars_to_cents(float(amount))
                    expense.date = str(txn["date"])
                    expense.category = category
                    count += 1
                else:
                    # Not found, so treat it as new
                    self.db.add(
                        ExpenseORM(
                            title=_clean_title(txn["name"]),
                            amount=dollars_to_cents(float(amount)),
                            date=str(txn["date"]),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    )
                    count += 1
            else:
                # Should be income
                if expense:
                    # Sign flipped: it was an expense, now it's income. Delete the old one, create a new one.
                    self.db.delete(expense)
                    self.db.add(
                        IncomeORM(
                            title=_clean_title(txn["name"]),
                            amount=dollars_to_cents(-float(amount)),
                            date=str(txn["date"]),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    )
                    count += 1
                elif income:
                    income.title = _clean_title(txn["name"])
                    income.amount = dollars_to_cents(-float(amount))
                    income.date = str(txn["date"])
                    income.category = category
                    count += 1
                else:
                    self.db.add(
                        IncomeORM(
                            title=_clean_title(txn["name"]),
                            amount=dollars_to_cents(-float(amount)),
                            date=str(txn["date"]),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    )
                    count += 1

        return count

    def _process_removed(self, transactions: list[dict], account_id: int) -> int:
        """Delete transactions by ``plaid_transaction_id``."""
        count = 0
        for txn in transactions:
            plaid_txn_id = txn.get("transaction_id")
            if not plaid_txn_id:
                continue

            # Try expenses
            expense = self.db.execute(
                select(ExpenseORM).where(
                    ExpenseORM.account_id == account_id,
                    ExpenseORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()
            if expense:
                self.db.delete(expense)
                count += 1
                continue

            # Try income
            income = self.db.execute(
                select(IncomeORM).where(
                    IncomeORM.account_id == account_id,
                    IncomeORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()
            if income:
                self.db.delete(income)
                count += 1

        return count
