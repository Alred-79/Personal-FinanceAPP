"""Plaid integration service. Built on the ORM, syncs with a cursor.

Takes a ``Session`` in ``__init__`` instead of the old ``BaseDatabridge``
singleton.

Sign convention (Plaid to Finance-Tracker):
    Plaid ``amount > 0``  → Expense (money leaving the account)
    Plaid ``amount < 0``  → Income  (money entering the account)
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.src.databridge.plaid_client import PlaidClient
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Token as TokenORM,
)
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.models import UserInDB
from server.src.services import plaid_crypto
from server.src.services.categorization_service import (
    CategorizationService,
    canonicalize_category,
)
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

# ── In-progress sync guard (single-worker invariant) ──────────────────────────
# A per-token in-process lock so two concurrent sync kicks (the background task
# fired by exchange + a user-triggered /sync, say) don't both process the same
# cursor batch and double-insert. It is module-level and in-memory: like the
# slowapi limiter and the MCP throttles it assumes ONE worker (Steps 02/05/09);
# >1 worker needs a DB advisory lock or a per-token in-progress row instead.
# The DB unique index is the real correctness backstop — this lock just avoids
# wasted duplicate work and IntegrityError churn within a process.
_sync_guard_lock = threading.Lock()
_tokens_syncing: set[int] = set()

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


def _is_pending(txn: dict) -> bool:
    """Whether a Plaid transaction is still pending.

    Pending transactions are excluded from the game event log entirely — they
    emit nothing here and will render as "fog" in package 08. Plaid sets
    ``pending`` true while a charge is authorizing; a missing flag is treated as
    posted (the conservative default for legacy feeds that omit it).
    """
    return bool(txn.get("pending", False))


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
        # Decrypt the access token only at the boundary, right before the Plaid
        # call. Never log the decrypted value.
        access_token = plaid_crypto.decrypt(token.key)  # type: ignore[arg-type]
        accounts = self.plaid.get_balance(access_token)
        if not accounts:
            return None
        return accounts[0].to_dict()

    # ------------------------------------------------------------------
    # Sync driven by a cursor
    # ------------------------------------------------------------------

    def _account_map_for_token(self, token: TokenORM) -> dict[str, int]:
        """Build a ``{plaid_account_id: local accounts.id}`` map for this item.

        Step 08: routing is by Plaid ``account_id``, not by shared name. A single
        Plaid item can span checking + savings + a card, each its own local
        Account carrying its ``plaid_account_id`` (set at exchange time). The
        empty string key (legacy accounts with no stored plaid_account_id) is
        skipped so a manually-renamed pre-Step-08 account isn't matched by an
        empty id.
        """
        rows = (
            self.db.execute(
                select(AccountORM.id, AccountORM.plaid_account_id).where(
                    AccountORM.user_id == token.user_id,
                    AccountORM.plaid_account_id.is_not(None),
                )
            )
        ).all()
        return {str(pid): int(aid) for aid, pid in rows if pid}

    def _fallback_account_for_token(self, token: TokenORM) -> Optional[int]:
        """Legacy name-keyed resolution for a token with no mapped accounts.

        A pre-Step-08 link stored no ``plaid_account_id``, so its account is
        still matched by the shared ``Token.name == Account.name`` convention.
        This keeps already-linked (un-migrated) accounts syncing until the next
        re-link writes a ``plaid_account_id``. New links route by id.
        """
        return self.db.execute(
            select(AccountORM.id).where(
                AccountORM.user_id == token.user_id,
                AccountORM.name == token.name,
            )
        ).scalar_one_or_none()

    def _refresh_balances(self, token: TokenORM, account_map: dict[str, int]) -> None:
        """Fetch the item's balances and update each mapped local account.

        Uses an issued atomic UPDATE per account (Step 06 convention) so a
        concurrent adjustment can't lose this write. Best-effort: a balance
        fetch failure is logged and swallowed so it never aborts an otherwise
        good transaction sync.
        """
        try:
            access_token = plaid_crypto.decrypt(token.key)  # type: ignore[arg-type]
            plaid_accounts = self.plaid.get_balance(access_token)
        except Exception:  # noqa: BLE001 — balance refresh is best-effort
            logger.exception(
                "balance refresh failed for token %s; transactions still applied",
                token.id,
            )
            return
        for pa in plaid_accounts or []:
            data = pa.to_dict() if hasattr(pa, "to_dict") else pa
            plaid_account_id = str(data.get("account_id") or "")
            local_id = account_map.get(plaid_account_id)
            if local_id is None:
                continue
            balances = data.get("balances") or {}
            available = balances.get("available")
            current = balances.get("current")
            value = available if available is not None else current
            if value is None:
                continue
            self.db.execute(
                update(AccountORM)
                .where(AccountORM.id == local_id)
                .values(
                    balance=dollars_to_cents(float(value)),
                    last_updated=func.current_timestamp(),
                )
            )

    def sync_token(self, token: TokenORM) -> dict:
        """Run a sync (driven by a cursor) for a single Plaid token or item.

        Returns a summary dict ``{"added": N, "modified": N, "removed": N}``.
        """
        # ── In-progress guard ────────────────────────────────────────────────
        # Skip if another in-process sync already holds this token, so two
        # concurrent kicks don't both process the same cursor batch (the DB
        # unique index is the hard backstop; this just avoids wasted churn).
        with _sync_guard_lock:
            if token.id in _tokens_syncing:
                logger.info(
                    "sync already in progress for token %s; skipping", token.id
                )
                return {"added": 0, "modified": 0, "removed": 0}
            _tokens_syncing.add(int(token.id))
        try:
            return self._sync_token_inner(token)
        finally:
            with _sync_guard_lock:
                _tokens_syncing.discard(int(token.id))

    def _sync_token_inner(self, token: TokenORM) -> dict:
        # Route each transaction to its OWN local account by Plaid account_id.
        account_map = self._account_map_for_token(token)

        # Legacy fallback: an un-migrated link (no plaid_account_id) still maps
        # to its single name-matched account so it keeps syncing.
        fallback_account_id = None
        if not account_map:
            fallback_account_id = self._fallback_account_for_token(token)
            if fallback_account_id is None:
                logger.warning(
                    "No local account found for token %s (%s); skipping sync.",
                    token.id,
                    token.name,
                )
                return {"added": 0, "modified": 0, "removed": 0}

        def resolve(txn: dict) -> Optional[int]:
            """Map a transaction's own Plaid account_id to a local account id."""
            if account_map:
                return account_map.get(str(txn.get("account_id") or ""))
            return fallback_account_id

        access_token = plaid_crypto.decrypt(token.key)  # type: ignore[arg-type]
        result = self.plaid.sync_transactions(
            access_token, token.cursor or ""
        )

        # Game event drafts collected during the CRUD apply. They are recorded
        # in the SAME transaction (Law 1: fold synchronously with the apply) so
        # the event log and the financial rows commit together or not at all.
        drafts: list[GameEventDraft] = []

        added = self._process_added(
            result.added, resolve, token.user_id, drafts
        )
        modified = self._process_modified(
            result.modified, resolve, token.user_id, drafts
        )
        removed = self._process_removed(result.removed, resolve, drafts)

        # Refresh each mapped account's balance from Plaid so forecasts and
        # Safe-to-Spend run off the live balance, not the link-time snapshot.
        if account_map:
            self._refresh_balances(token, account_map)

        # Record the game events (posted txns, corrections, reversals). This is
        # best-effort: a fold bug must never break the finance sync, so a failure
        # here is logged and swallowed — the financial rows are already applied.
        if drafts:
            try:
                record_events(self.db, drafts)
            except Exception:  # noqa: BLE001 — game layer is best-effort
                logger.exception(
                    "game event recording failed during sync for token %s",
                    token.id,
                )

        # Persist the cursor so the next sync is incremental.
        token.cursor = result.next_cursor

        return {"added": added, "modified": modified, "removed": removed}

    def sync_all_tokens(self, current_user: UserInDB) -> list[dict]:
        """Sync every Plaid token or item owned by *current_user*.

        Returns one summary dict per token. Each token's sync is isolated in its
        own SAVEPOINT, so one item's ``ITEM_LOGIN_REQUIRED`` / network failure
        rolls back ONLY that token's partial work and does not abort the others
        (the report's "one bad token aborts all" finding).
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
            try:
                with self.db.begin_nested():
                    summary = self.sync_token(token)
                summaries.append({"token": token.name, **summary})
            except Exception:  # noqa: BLE001 — isolate one failing item
                logger.exception(
                    "sync failed for token %s (%s); other tokens unaffected",
                    token.id,
                    token.name,
                )
                summaries.append(
                    {
                        "token": token.name,
                        "added": 0,
                        "modified": 0,
                        "removed": 0,
                        "error": "sync_failed",
                    }
                )

        return summaries

    # ── Game event hooks (v4 package 01) ───────────────────────────────
    #
    # These translate Plaid sync deltas into game-domain events on the
    # 'sync' stream. The events are recorded in the same transaction as the
    # CRUD apply (see sync_token). Pending transactions emit nothing.

    def _find_posted_event(self, plaid_txn_id: str):
        """The original ``TxnPosted`` event id for a Plaid txn, if any.

        Corrections/reversals set ``caused_by`` to this so the chain is
        traceable and the reversal can compute compensation from the ORIGINAL
        payload, never from current projection state.
        """
        from server.src.db.models import GameEvent

        return self.db.execute(
            select(GameEvent)
            .where(
                GameEvent.type == "TxnPosted",
                GameEvent.idempotency_key
                == f"plaid:{plaid_txn_id}:posted",
            )
        ).scalar_one_or_none()

    def _emit_posted(
        self,
        drafts: list[GameEventDraft] | None,
        txn: dict,
        account_id: int,
        kind: str,
        amount_cents: int,
        category: str,
    ) -> None:
        """Append a ``TxnPosted`` draft for a newly inserted POSTED txn.

        No-op when *drafts* is None (callers that don't record events) or when
        the txn is still pending (pending emits nothing — package 08 fog).
        """
        if drafts is None or _is_pending(txn):
            return
        plaid_txn_id = txn["transaction_id"]
        drafts.append(
            GameEventDraft(
                stream="sync",
                type="TxnPosted",
                payload={
                    "plaid_transaction_id": plaid_txn_id,
                    "account_id": account_id,
                    "kind": kind,  # 'expense' | 'income'
                    "amount_cents": amount_cents,
                    "category": category,
                    "date": str(txn.get("date")),
                },
                idempotency_key=f"plaid:{plaid_txn_id}:posted",
            )
        )

    def _emit_correction(
        self,
        drafts: list[GameEventDraft] | None,
        txn: dict,
        account_id: int,
        new_amount_cents: int,
        new_category: str,
    ) -> None:
        """Append a ``TxnCorrected`` draft for a modified posted txn.

        Computes ``field_deltas`` against the original ``TxnPosted`` payload so
        folds consume the delta, not absolute state. No-op for pending txns or
        txns with no recorded ``TxnPosted`` (nothing to correct).
        """
        if drafts is None or _is_pending(txn):
            return
        plaid_txn_id = txn["transaction_id"]
        original = self._find_posted_event(plaid_txn_id)
        if original is None:
            return
        import json as _json

        orig_payload = _json.loads(original.payload)
        old_amount = orig_payload.get("amount_cents", 0)
        field_deltas: dict = {}
        if new_amount_cents != old_amount:
            field_deltas["amount_cents"] = new_amount_cents - old_amount
        if new_category != orig_payload.get("category"):
            field_deltas["category"] = {
                "from": orig_payload.get("category"),
                "to": new_category,
            }
        if not field_deltas:
            return  # nothing actually changed
        drafts.append(
            GameEventDraft(
                stream="sync",
                type="TxnCorrected",
                payload={
                    "plaid_transaction_id": plaid_txn_id,
                    "account_id": account_id,
                    "field_deltas": field_deltas,
                },
                idempotency_key=(
                    f"plaid:{plaid_txn_id}:corrected:"
                    f"{txn.get('date')}:{new_amount_cents}"
                ),
                caused_by=original.id,
            )
        )

    def _emit_reversal(
        self,
        drafts: list[GameEventDraft] | None,
        plaid_txn_id: str,
        account_id: int,
    ) -> None:
        """Append a ``TxnReversed`` draft for a removed posted txn.

        Compensation is computed downstream from the ORIGINAL ``TxnPosted``
        payload (carried here as ``original_amount_cents``), never from current
        projection state. No-op when no ``TxnPosted`` was recorded.
        """
        if drafts is None:
            return
        original = self._find_posted_event(plaid_txn_id)
        if original is None:
            return
        import json as _json

        orig_payload = _json.loads(original.payload)
        drafts.append(
            GameEventDraft(
                stream="sync",
                type="TxnReversed",
                payload={
                    "plaid_transaction_id": plaid_txn_id,
                    "account_id": account_id,
                    "original_amount_cents": orig_payload.get("amount_cents", 0),
                    "original_kind": orig_payload.get("kind"),
                },
                idempotency_key=f"plaid:{plaid_txn_id}:reversed",
                caused_by=original.id,
            )
        )

    # ── Helpers ────────────────────────────────────────────────────────

    def _insert_deduped(self, row) -> bool:
        """Insert *row* in a SAVEPOINT; on the partial-unique collision skip it.

        Replaces the old check-then-insert (TOCTOU). Two concurrent syncs that
        both reach insert for the same ``plaid_transaction_id`` can't both win —
        the loser hits ``IntegrityError`` on the partial unique index and is
        rolled back to the SAVEPOINT (leaving the surrounding sync transaction
        intact) and skipped. Returns True if the row was inserted.
        """
        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()  # force the index check now, inside the SAVEPOINT
        except IntegrityError:
            return False
        return True

    def _run_rules_on_synced(
        self, user_id: int | None, tx_type: str, row
    ) -> None:
        """Run the v1 rule engine on a freshly synced row (Step 08).

        Mirrors the manual-entry path (``TransactionService.create`` →
        ``RuleEngine.run_on_transaction``). The engine's ``rule_executions``
        unique key makes this idempotent on re-sync, so a re-imported txn never
        double-fires a money-moving rule. Best-effort: ``run_on_transaction``
        never raises, but guard anyway so a rules problem can't break sync.
        """
        if user_id is None or row.id is None:
            return
        try:
            RuleEngine(self.db).run_on_transaction(
                user_id,
                tx_type,
                int(row.id),
                {
                    "id": int(row.id),
                    "title": row.title,
                    "amount": cents_to_dollars(row.amount),
                    "date": row.date,
                    "category": row.category,
                    "account_id": row.account_id,
                    "type": tx_type,
                },
            )
        except Exception:  # noqa: BLE001 — rules never break sync
            logger.exception(
                "rule engine failed on synced %s:%s", tx_type, row.id
            )

    def _process_added(
        self,
        transactions: list[dict],
        resolve,
        user_id: int | None = None,
        drafts: list[GameEventDraft] | None = None,
    ) -> int:
        """Insert new transactions, deduplicating on ``plaid_transaction_id``.

        *resolve* maps a transaction dict to the local ``accounts.id`` it belongs
        to (by the txn's own Plaid ``account_id``); a txn whose account isn't
        mapped locally is skipped (logged).

        When *user_id* is given, expenses are categorized through the
        categorizer (a user's learned rename first, then built-in keyword rules),
        falling back to Plaid's own category — canonicalized to the app's
        taxonomy — so a manual rename keeps sticking on later syncs. Without a
        *user_id* the canonicalized Plaid category is used as-is.

        When *drafts* is given, every newly inserted **posted** transaction
        appends a ``TxnPosted`` event draft (pending transactions emit nothing).
        The v1 rule engine also fires on each inserted row (idempotent via
        ``rule_executions``), matching the manual-entry path.
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
            account_id = resolve(txn)
            if account_id is None:
                logger.warning(
                    "No local account for Plaid txn %s (account_id=%s); skipping.",
                    txn.get("transaction_id"),
                    txn.get("account_id"),
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
                row = ExpenseORM(
                    title=_clean_title(txn["name"]),
                    amount=dollars_to_cents(float(amount)),
                    date=str(txn["date"]),
                    category=category,
                    plaid_transaction_id=plaid_txn_id,
                    account_id=account_id,
                )
                if self._insert_deduped(row):
                    count += 1
                    self._emit_posted(
                        drafts, txn, account_id, "expense",
                        dollars_to_cents(float(amount)), category,
                    )
                    self._run_rules_on_synced(user_id, "expense", row)
            else:
                # Income (money entering account)
                row = IncomeORM(
                    title=_clean_title(txn["name"]),
                    amount=dollars_to_cents(-float(amount)),
                    date=str(txn["date"]),
                    category=category,
                    plaid_transaction_id=plaid_txn_id,
                    account_id=account_id,
                )
                if self._insert_deduped(row):
                    self._emit_posted(
                        drafts, txn, account_id, "income",
                        dollars_to_cents(-float(amount)), category,
                    )
                    self._run_rules_on_synced(user_id, "income", row)
                    count += 1

        return count

    def _process_modified(
        self,
        transactions: list[dict],
        resolve,
        user_id: int | None = None,
        drafts: list[GameEventDraft] | None = None,
    ) -> int:
        """Update existing transactions by ``plaid_transaction_id``.

        *resolve* maps a txn dict to its local ``accounts.id`` (Step 08 routing).

        When *user_id* is given, the category is resolved through the same
        categorizer the *added* path uses, so a user's learned rename WINS over
        Plaid's re-guess on a modify (preserving the manual edit). Without it,
        the canonicalized Plaid category is used. Amount/date/title remain
        bank-authoritative (the bank is the source of truth for those).

        When *drafts* is given, a ``TxnCorrected`` event is appended for each
        posted txn that actually changed against its original ``TxnPosted``.
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
            account_id = resolve(txn)
            if account_id is None:
                logger.warning(
                    "No local account for modified Plaid txn %s (account_id=%s); skipping.",
                    txn.get("transaction_id"),
                    txn.get("account_id"),
                )
                continue
            plaid_txn_id = txn["transaction_id"]
            category = _extract_category(txn)
            # Respect a user's learned rename on modify (don't clobber a manual
            # category with Plaid's re-guess); falls back to Plaid's category.
            if categorizer is not None:
                assert user_id is not None
                category = categorizer.categorize(
                    user_id, txn["name"], default=category, use_llm=False
                )[0]
            amount = txn["amount"]
            # New signed amount in cents: expense (amount>=0) positive, income
            # negative — matches how _process_added stored amount_cents.
            new_amount_cents = (
                dollars_to_cents(float(amount))
                if amount >= 0
                else dollars_to_cents(-float(amount))
            )
            self._emit_correction(
                drafts, txn, account_id, new_amount_cents, category
            )

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

    def _process_removed(
        self,
        transactions: list[dict],
        resolve,
        drafts: list[GameEventDraft] | None = None,
    ) -> int:
        """Delete transactions by ``plaid_transaction_id``.

        A removed txn carries only its ``transaction_id`` (no amount/account in
        Plaid's removed payload), and ``plaid_transaction_id`` is globally unique
        per item, so deletion is keyed by that id alone — no account scoping is
        needed and the *resolve* signature is kept only for call-site symmetry.

        When *drafts* is given, a ``TxnReversed`` event is appended for each
        removed txn that had a recorded ``TxnPosted`` (compensation computed
        downstream from the original payload, never from current state).
        """
        count = 0
        for txn in transactions:
            plaid_txn_id = txn.get("transaction_id")
            if not plaid_txn_id:
                continue

            # Try expenses (keyed by the globally-unique Plaid txn id).
            expense = self.db.execute(
                select(ExpenseORM).where(
                    ExpenseORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()
            if expense:
                acct_id = expense.account_id
                self.db.delete(expense)
                count += 1
                self._emit_reversal(drafts, plaid_txn_id, acct_id)
                continue

            # Try income
            income = self.db.execute(
                select(IncomeORM).where(
                    IncomeORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()
            if income:
                acct_id = income.account_id
                self.db.delete(income)
                count += 1
                self._emit_reversal(drafts, plaid_txn_id, acct_id)

        return count
