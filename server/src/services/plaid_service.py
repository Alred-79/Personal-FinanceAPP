"""Plaid integration service. Built on the ORM, syncs with a cursor.

Takes a ``Session`` in ``__init__`` instead of the old ``BaseDatabridge``
singleton.

Sign convention (Plaid to Finance-Tracker):
    Plaid ``amount > 0``  → Expense (money leaving the account)
    Plaid ``amount < 0``  → Income  (money entering the account)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

from cryptography.fernet import InvalidToken
from plaid.exceptions import ApiException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.src.databridge.plaid_client import PlaidClient
from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Notification as NotificationORM,
    Token as TokenORM,
)
from server.src.db.rls import advisory_unlock, try_advisory_lock
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.models import UserInDB
from server.src.services import plaid_crypto
from server.src.services.categorization_service import (
    CategorizationService,
    canonicalize_category,
)
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.rule_engine import RuleEngine
from server.src.services.account_semantics import infer_semantic_role

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


# Plaid error codes that mean "this item needs the user to re-authenticate" —
# a re-link notice is the right response, not an opaque retry/fail.
_RELINK_ERROR_CODES = {"ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN"}
# A transient code Plaid returns before the product's data is ready; worth ONE
# short bounded retry (we run in a sync BackgroundTask thread).
_RETRYABLE_ERROR_CODE = "PRODUCT_NOT_READY"
_PRODUCT_NOT_READY_BACKOFF_SECONDS = 2.0


def _plaid_error_code(exc: "ApiException") -> Optional[str]:
    """Best-effort ``error_code`` from a Plaid ``ApiException`` body.

    The body is JSON like ``{"error_code": "ITEM_LOGIN_REQUIRED", ...}`` but may
    be malformed or empty; never raise from the parse — fall back to ``None`` so
    the caller treats it as a generic failure.
    """
    body = getattr(exc, "body", None)
    if not body:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):
        code = data.get("error_code")
        return code if isinstance(code, str) else None
    return None


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
        # call. Never log the decrypted value. A token that won't decrypt (B3)
        # surfaces a re-link notice and returns None (router → no data), not a 500.
        try:
            access_token = plaid_crypto.decrypt(token.key)  # type: ignore[arg-type]
        except InvalidToken:
            logger.warning(
                "plaid get_balance: token %s won't decrypt; emitting re-link notice",
                token.id,
            )
            self._notify_relink(token.user_id, token.id)
            return None
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
        except InvalidToken:
            # B3 — a decrypt failure here is not a transient balance hiccup; the
            # token is unusable. Surface a re-link notice rather than silently
            # skipping, then bail (transactions for this token are already applied
            # by the caller path; balance just won't refresh).
            logger.warning(
                "balance refresh: token %s won't decrypt; emitting re-link notice",
                token.id,
            )
            self._notify_relink(token.user_id, token.id)
            return
        try:
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
            limit = balances.get("limit")
            value = current if current is not None else available
            if value is None:
                continue
            account_type = str(data.get("type") or "unknown")
            account_subtype = (
                str(data.get("subtype")) if data.get("subtype") is not None else None
            )
            self.db.execute(
                update(AccountORM)
                .where(AccountORM.id == local_id)
                .values(
                    balance=dollars_to_cents(float(value)),
                    type=account_type,
                    subtype=account_subtype,
                    current_balance=(
                        dollars_to_cents(float(current)) if current is not None else None
                    ),
                    available_balance=(
                        dollars_to_cents(float(available)) if available is not None else None
                    ),
                    credit_limit=(
                        dollars_to_cents(float(limit)) if limit is not None else None
                    ),
                    iso_currency_code=balances.get("iso_currency_code"),
                    unofficial_currency_code=balances.get("unofficial_currency_code"),
                    balance_source="plaid",
                    balance_observed_at=func.current_timestamp(),
                    semantic_role=infer_semantic_role(account_type, account_subtype),
                    review_state="confirmed",
                    last_updated=func.current_timestamp(),
                    plaid_balance_refreshed_at=func.current_timestamp(),
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

        # B3 — decrypt only at the boundary; a stored token that won't decrypt
        # (e.g. JWT secret rotated without PLAID_TOKEN_KEY) must not crash the
        # whole run. Surface a re-link notice and skip just this token.
        try:
            access_token = plaid_crypto.decrypt(token.key)  # type: ignore[arg-type]
        except InvalidToken:
            logger.warning(
                "plaid sync: token %s won't decrypt; emitting re-link notice",
                token.id,
            )
            self._notify_relink(token.user_id, token.id)
            return {"added": 0, "modified": 0, "removed": 0}
        # L5 — per-page cursor checkpointing under a session-level advisory lock.
        # Each page is applied and its cursor committed BEFORE the next is fetched,
        # so a mid-pagination failure resumes from the last good page (not a full
        # re-pull from "") and a large initial pull doesn't buffer the whole item
        # in one transaction. The advisory lock (Postgres; no-op on SQLite) stops a
        # second worker from racing the same token's cursor across those commits.
        if not try_advisory_lock(self.db, int(token.id)):
            logger.info(
                "plaid sync: token %s advisory-locked by another worker; skipping",
                token.id,
            )
            return {"added": 0, "modified": 0, "removed": 0}

        added = modified = removed = skipped = 0
        any_added_or_modified = False
        try:
            pages = self._iter_sync_pages(access_token, token)
            for page in pages:
                # Apply one page atomically in a SAVEPOINT so a mid-page failure
                # rolls back ONLY that page's partial work (not prior committed
                # pages, not the rest of the session), then commit it as a durable
                # checkpoint before fetching the next page.
                with self.db.begin_nested():
                    drafts: list[GameEventDraft] = []
                    a, a_sk = self._process_added(
                        page.added, resolve, token.user_id, drafts
                    )
                    m, m_sk = self._process_modified(
                        page.modified, resolve, token.user_id, drafts
                    )
                    r = self._process_removed(page.removed, resolve, drafts)
                    # Record this page's game events in the SAME (nested) txn as its
                    # apply (Law 1). Best-effort: a fold bug must never break sync.
                    if drafts:
                        try:
                            record_events(self.db, drafts)
                        except Exception:  # noqa: BLE001 — game layer best-effort
                            logger.exception(
                                "game event recording failed during sync for "
                                "token %s", token.id,
                            )
                    token.cursor = page.next_cursor
                added += a
                modified += m
                removed += r
                skipped += a_sk + m_sk
                any_added_or_modified = any_added_or_modified or bool(a or m)
                # Checkpoint: commit this page (+ its cursor) before the next fetch.
                # The next sync resumes here even if a later page / the process fails.
                self.db.commit()

            # After all pages land: refresh balances + reconcile Bridges ONCE.
            # Both are aggregate + idempotent + best-effort, so deferring them to
            # the end (and to the next sync if pagination failed mid-way) is safe.
            if account_map:
                self._refresh_balances(token, account_map)
            if any_added_or_modified:
                try:
                    self._reconcile_bridges(token.user_id)
                except Exception:  # noqa: BLE001 — Bridge reconcile is best-effort
                    logger.exception(
                        "bridge reconciliation failed during sync for token %s",
                        token.id,
                    )
            self.db.commit()
        finally:
            # Release the session-level advisory lock. If a page failed, the PG
            # transaction is aborted and the unlock statement can't run until we
            # roll back — do so (committed pages are already durable) so the lock
            # is never leaked onto the pooled connection.
            try:
                advisory_unlock(self.db, int(token.id))
            except Exception:  # noqa: BLE001
                self.db.rollback()
                try:
                    advisory_unlock(self.db, int(token.id))
                except Exception:  # noqa: BLE001 — last resort; conn-close frees it
                    logger.exception(
                        "failed to release advisory lock for token %s", token.id
                    )

        summary = {"added": added, "modified": modified, "removed": removed}
        # Surface malformed-row drops (B2) so they aren't silent. Omit when zero
        # to keep the common-case summary unchanged for existing callers/tests.
        if skipped:
            summary["skipped"] = skipped
        return summary

    def _iter_sync_pages(self, access_token: str, token: TokenORM):
        """Yield Plaid sync pages, applying the B4 PRODUCT_NOT_READY retry to the
        FIRST page fetch (the warming-up case happens at the start of a cycle).

        Wrapping the generator lets ``_sync_token_inner`` consume pages while the
        bounded retry still covers the initial ``transactions_sync`` call.
        """
        try:
            gen = self.plaid.sync_transactions_pages(access_token, token.cursor or "")
            first = next(gen, None)
        except ApiException as exc:
            if _plaid_error_code(exc) != _RETRYABLE_ERROR_CODE:
                raise
            logger.info(
                "plaid sync: token %s PRODUCT_NOT_READY; one bounded retry",
                token.id,
            )
            time.sleep(_PRODUCT_NOT_READY_BACKOFF_SECONDS)
            gen = self.plaid.sync_transactions_pages(access_token, token.cursor or "")
            first = next(gen, None)
        if first is None:
            return
        yield first
        yield from gen

    def _reconcile_bridges(self, user_id: int | None) -> None:
        """Feed the user's recent ledger to the Bridge reconciler (Pillar 2C).

        Rather than thread a collector through the hot insertion path, we pass the
        user's recent transactions (a small window) as signed ``amount_cents``
        (+in / −out) rows. ``reconcile`` only touches OPEN Bridges and dedups by
        status, so re-feeding rows on a later sync is idempotent — a Bridge already
        ``verified`` is never re-counted. Lazy import keeps the engine/assistant
        import graph clean.
        """
        if user_id is None:
            return
        from server.src.services.assisted_action_service import (
            AssistedActionService,
        )

        # Only do work if there's an open Bridge to reconcile (cheap guard).
        svc = AssistedActionService(self.db)
        if not svc.list(user_id, open_only=True):
            return

        rows: list[dict] = []
        for exp in (
            self.db.execute(
                select(
                    ExpenseORM.id,
                    ExpenseORM.title,
                    ExpenseORM.amount,
                    ExpenseORM.date,
                    ExpenseORM.account_id,
                )
                .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
                .where(AccountORM.user_id == user_id)
                .order_by(ExpenseORM.id.desc())
                .limit(200)
            ).all()
        ):
            rows.append(
                {
                    "id": exp.id,
                    "title": exp.title,
                    "amount_cents": -int(exp.amount or 0),  # out
                    "date": exp.date,
                    "account_id": exp.account_id,
                }
            )
        for inc in (
            self.db.execute(
                select(
                    IncomeORM.id,
                    IncomeORM.title,
                    IncomeORM.amount,
                    IncomeORM.date,
                    IncomeORM.account_id,
                )
                .join(AccountORM, IncomeORM.account_id == AccountORM.id)
                .where(AccountORM.user_id == user_id)
                .order_by(IncomeORM.id.desc())
                .limit(200)
            ).all()
        ):
            rows.append(
                {
                    "id": inc.id,
                    "title": inc.title,
                    "amount_cents": int(inc.amount or 0),  # in
                    "date": inc.date,
                    "account_id": inc.account_id,
                }
            )
        svc.reconcile(user_id, rows)

    def sync_all_tokens(self, current_user: UserInDB) -> list[dict]:
        """Sync every Plaid token or item owned by *current_user*.

        Returns one summary dict per token. One item's failure does not abort the
        others (the report's "one bad token aborts all" finding): each token is
        wrapped in its own try/except, and L5's per-page commits mean a token's
        successfully-applied pages are already durable when a later page fails —
        the next sync resumes from the last good cursor. (We can no longer wrap a
        token in a SAVEPOINT here because ``sync_token`` commits per page; a roll
        back of the whole token's work is neither possible nor desired now that
        each page is a durable checkpoint.) On entry we roll back any pending
        state so a prior token's partial work can't ride along.
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
                summary = self.sync_token(token)
                summaries.append({"token": token.name, **summary})
            except ApiException as exc:
                # B4 — differentiate Plaid errors. A re-auth code gets a re-link
                # notice (actionable) instead of an opaque "sync_failed". The
                # notice is added in its OWN savepoint so the failed token's
                # rolled-back work doesn't take the notification with it.
                code = _plaid_error_code(exc)
                logger.warning(
                    "plaid sync: token %s failed with ApiException code=%s",
                    token.id,
                    code,
                )
                if code in _RELINK_ERROR_CODES:
                    try:
                        with self.db.begin_nested():
                            self._notify_relink(token.user_id, token.id)
                    except Exception:  # noqa: BLE001 — notice is best-effort
                        logger.exception(
                            "failed to emit re-link notice for token %s", token.id
                        )
                summaries.append(
                    {
                        "token": token.name,
                        "added": 0,
                        "modified": 0,
                        "removed": 0,
                        "error": "relink_required" if code in _RELINK_ERROR_CODES
                        else (code or "sync_failed"),
                    }
                )
            except Exception:  # noqa: BLE001 — isolate one failing item
                # Each page applied in its own SAVEPOINT + commit, so a failure
                # leaves the session at a clean committed boundary (prior pages
                # durable) — no rollback of the whole session needed; resume next
                # sync from the last good cursor.
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
        orig_payload = json.loads(original.payload)
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
            tx_view = {
                "id": int(row.id),
                "title": row.title,
                "amount": cents_to_dollars(row.amount),
                "date": row.date,
                "category": row.category,
                "account_id": row.account_id,
                "type": tx_type,
            }
            # W5: income rows carry their tax/earnings character so a Tax-Reserve
            # allocate rule (source_type == self_employment) can fire on synced
            # income too. Absent on expenses by construction.
            if tx_type == "income":
                tx_view["source_type"] = getattr(row, "source_type", None)
            RuleEngine(self.db).run_on_transaction(
                user_id, tx_type, int(row.id), tx_view
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
    ) -> tuple[int, int]:
        """Insert new transactions, deduplicating on ``plaid_transaction_id``.

        Returns ``(applied_count, skipped_count)`` — skipped rows are malformed
        (missing id/amount/date) and surfaced so silent drops are visible.

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
        skipped = 0
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
            # B2 — parse-then-mutate: read required fields defensively and skip a
            # malformed row before any DB mutation. Never log the full txn (PII).
            plaid_txn_id = txn.get("transaction_id")
            amount = txn.get("amount")
            if plaid_txn_id is None or amount is None:
                logger.warning("plaid sync: skipping added row missing id/amount")
                skipped += 1
                continue
            txn_date = txn.get("date")
            if txn_date is None:
                logger.warning(
                    "plaid sync: skipping added row missing date %s", plaid_txn_id
                )
                skipped += 1
                continue
            title = _clean_title(txn.get("name"))  # _clean_title is None-safe
            category = _extract_category(txn)

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
                        user_id, title, default=category, use_llm=False
                    )[0]
                row = ExpenseORM(
                    title=title,
                    amount=dollars_to_cents(float(amount)),
                    date=str(txn_date),
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
                    title=title,
                    amount=dollars_to_cents(-float(amount)),
                    date=str(txn_date),
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

        if skipped:
            logger.warning(
                "plaid sync: %d added row(s) skipped (missing id/amount/date)",
                skipped,
            )
        return count, skipped

    def _process_modified(
        self,
        transactions: list[dict],
        resolve,
        user_id: int | None = None,
        drafts: list[GameEventDraft] | None = None,
    ) -> tuple[int, int]:
        """Update existing transactions by ``plaid_transaction_id``.

        Returns ``(applied_count, skipped_count)`` — malformed rows (missing
        id/amount/date) are skipped before any DB mutation and counted.

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
        skipped = 0
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
            # B2 — parse-then-mutate: read the required fields defensively and
            # skip a malformed row BEFORE touching self.db (the modify path
            # mutates rows directly, with no SAVEPOINT), so a bad row never leaves
            # the session dirty. Never log the full txn (PII) — the id only.
            plaid_txn_id = txn.get("transaction_id")
            amount = txn.get("amount")
            if plaid_txn_id is None or amount is None:
                logger.warning("plaid sync: skipping modified row missing id/amount")
                skipped += 1
                continue
            txn_date = txn.get("date")
            if txn_date is None:
                logger.warning(
                    "plaid sync: skipping modified row missing date %s", plaid_txn_id
                )
                skipped += 1
                continue
            title = _clean_title(txn.get("name"))  # _clean_title is None-safe
            category = _extract_category(txn)
            # Respect a user's learned rename on modify (don't clobber a manual
            # category with Plaid's re-guess); falls back to Plaid's category.
            if categorizer is not None:
                assert user_id is not None
                category = categorizer.categorize(
                    user_id, title, default=category, use_llm=False
                )[0]
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

            # B1 — key the lookup on plaid_transaction_id ALONE (the unique index
            # and _process_removed are global, not account-scoped). Plaid can
            # report a modify under a DIFFERENT account_id than the original was
            # stored under; an account-scoped lookup would miss it, fall to
            # "treat as new", and collide with the global index — aborting the
            # whole token sync. Expense-first precedence (as before).
            expense = self.db.execute(
                select(ExpenseORM).where(
                    ExpenseORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()

            income = self.db.execute(
                select(IncomeORM).where(
                    IncomeORM.plaid_transaction_id == plaid_txn_id,
                )
            ).scalar_one_or_none()

            if amount >= 0:
                # Should be an expense
                if income:
                    # Sign flipped: it was income, now it's an expense. Delete the
                    # old row; insert the new via the dedup helper so a residual
                    # global collision skips instead of aborting the sync.
                    self.db.delete(income)
                    if self._insert_deduped(
                        ExpenseORM(
                            title=title,
                            amount=dollars_to_cents(float(amount)),
                            date=str(txn_date),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    ):
                        count += 1
                    else:
                        logger.warning(
                            "plaid sync: modified->expense insert skipped (exists) %s",
                            plaid_txn_id,
                        )
                elif expense:
                    new_amount = dollars_to_cents(float(amount))
                    self._warn_if_overwriting(
                        user_id, expense, title, new_amount, plaid_txn_id
                    )
                    expense.title = title
                    expense.amount = new_amount
                    expense.date = str(txn_date)
                    expense.category = category
                    # Handle a cross-account move: adopt the new account.
                    if expense.account_id != account_id:
                        expense.account_id = account_id
                    count += 1
                else:
                    # Not found under any account → treat as new, deduped so a
                    # global-index collision skips instead of raising.
                    if self._insert_deduped(
                        ExpenseORM(
                            title=title,
                            amount=dollars_to_cents(float(amount)),
                            date=str(txn_date),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    ):
                        count += 1
                    else:
                        logger.warning(
                            "plaid sync: modified-as-new expense skipped (exists) %s",
                            plaid_txn_id,
                        )
            else:
                # Should be income
                if expense:
                    # Sign flipped: it was an expense, now it's income.
                    self.db.delete(expense)
                    if self._insert_deduped(
                        IncomeORM(
                            title=title,
                            amount=dollars_to_cents(-float(amount)),
                            date=str(txn_date),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    ):
                        count += 1
                    else:
                        logger.warning(
                            "plaid sync: modified->income insert skipped (exists) %s",
                            plaid_txn_id,
                        )
                elif income:
                    new_amount = dollars_to_cents(-float(amount))
                    self._warn_if_overwriting(
                        user_id, income, title, new_amount, plaid_txn_id
                    )
                    income.title = title
                    income.amount = new_amount
                    income.date = str(txn_date)
                    income.category = category
                    if income.account_id != account_id:
                        income.account_id = account_id
                    count += 1
                else:
                    if self._insert_deduped(
                        IncomeORM(
                            title=title,
                            amount=dollars_to_cents(-float(amount)),
                            date=str(txn_date),
                            category=category,
                            plaid_transaction_id=plaid_txn_id,
                            account_id=account_id,
                        )
                    ):
                        count += 1
                    else:
                        logger.warning(
                            "plaid sync: modified-as-new income skipped (exists) %s",
                            plaid_txn_id,
                        )

        if skipped:
            logger.warning(
                "plaid sync: %d modified row(s) skipped (missing id/amount/date)",
                skipped,
            )
        return count, skipped

    def _warn_if_overwriting(
        self,
        user_id: int | None,
        row,
        new_title: str,
        new_amount_cents: int,
        plaid_txn_id: str,
    ) -> None:
        """Warn the user when Plaid revises a bank-authoritative field (P1 #6).

        The category is already protected on modify (a learned rename wins via the
        categorizer). Amount/date/title stay bank-authoritative — Plaid IS the
        source of truth for the money and the bank's description — so we do **not**
        hard-drop the new Plaid data. But a user who manually corrected a title or
        amount would otherwise see it silently reverted (assessment P1 #6). So when
        an existing row's title or amount actually changes on a modify, we emit one
        idempotent ``plaid_revision`` notification telling them their bank revised a
        transaction and to re-check it — surfacing the change and letting them
        decide which value is right rather than reverting in silence.

        Idempotent by a stable ref keyed on the txn + the new amount, so re-syncing
        the same revision doesn't stack duplicate warnings, while a *later* revision
        with a different amount still gets its own warning. The ref intentionally
        does NOT embed ``new_title`` — a bank that micro-revises a description
        (whitespace/case churn) at the same amount would otherwise stack an
        unbounded pile of near-identical notifications; collapsing title-only churn
        at a fixed amount to a single notice is the desired anti-stacking behavior.
        """
        if user_id is None:
            return
        title_changed = (row.title or "") != new_title
        amount_changed = (row.amount or 0) != new_amount_cents
        if not (title_changed or amount_changed):
            return
        ref = f"plaid_revision:{plaid_txn_id}:{new_amount_cents}"
        exists = self.db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == user_id,
                NotificationORM.ref == ref,
            )
        ).scalar_one_or_none()
        if exists is not None:
            return
        old_dollars = cents_to_dollars(abs(row.amount or 0))
        new_dollars = cents_to_dollars(abs(new_amount_cents))
        if amount_changed:
            detail = (
                f"changed from ${old_dollars:,.2f} to ${new_dollars:,.2f}"
            )
        else:
            detail = f"renamed to “{new_title}”"
        self.db.add(
            NotificationORM(
                user_id=user_id,
                type="plaid_revision",
                title="Your bank revised a transaction",
                message=(
                    f"“{row.title}” was {detail} by your bank. If you'd edited it "
                    f"yourself, re-check it — your bank's version is now shown."
                ),
                ref=ref,
            )
        )

    def _notify_relink(self, user_id: int | None, token_id: int | None) -> None:
        """Emit one idempotent 're-link this bank' notification (B3/B4).

        Used when a token can no longer be used — the stored Plaid access token
        won't decrypt (e.g. JWT secret rotated without PLAID_TOKEN_KEY) or Plaid
        reports ITEM_LOGIN_REQUIRED / INVALID_ACCESS_TOKEN. Deduped on a stable
        ``ref`` per token so repeated failed syncs don't stack notices. NEVER
        references the secret — only the item. Best-effort: a notify failure must
        not mask the original error, so callers may wrap this in try/except.
        """
        if user_id is None or token_id is None:
            return
        ref = f"plaid_relink:{token_id}"
        exists = self.db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == user_id,
                NotificationORM.ref == ref,
            )
        ).scalar_one_or_none()
        if exists is not None:
            return
        self.db.add(
            NotificationORM(
                user_id=user_id,
                type="plaid_relink",
                title="Reconnect your bank",
                message=(
                    "We couldn't sync one of your linked banks. Please reconnect "
                    "it from Settings to resume automatic transaction updates."
                ),
                ref=ref,
            )
        )

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
