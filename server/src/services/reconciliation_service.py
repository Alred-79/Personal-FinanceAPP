"""The Reconciliation Desk — turn a messy statement into reconciled transactions.

Upload a bank-statement PDF / screenshot / pasted blob from *any* bank, even one
Plaid never reaches, and this service:

1. **extracts** the statement (vision for image/PDF-as-image, a text model for a
   pasted blob) into opening/closing balances + a list of rows,
2. **normalizes** every amount/date to whole signed cents (+in / -out),
3. **categorizes** each row through the existing 3-tier categorizer,
4. **dedups** against transactions already on the account (flag, never drop),
5. **reconciles** its own extraction against the statement's running balance —
   ``opening + Σtxns == closing`` — and, when a running-balance column exists,
   localizes the first row that breaks the running sum,
6. **persists** an ``ImportSession`` the user reviews before committing.

The differentiator is step 5: the agent does not claim success unless the
arithmetic closes, and when it doesn't it points at the offending row instead of
silently guessing. Everything money is integer cents, so the balance equality is
exact.

PII NOTE: the raw document bytes live only in memory for the request; only the
parsed rows persist (same stance as ``receipt_service``).

Every model call is injected (``vision_fn`` / ``text_llm_fn`` / the categorizer's
``llm_fn``) so the whole pipeline tests without the Groq SDK — mirroring
``receipt_service`` and its tests.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Account as AccountORM
from ..db.models import Expense as ExpenseORM
from ..db.models import Income as IncomeORM
from ..db.models import ImportRow as ImportRowORM
from ..db.models import ImportSession as ImportSessionORM
from ..money import dollars_to_cents
from .categorization_service import (
    CategorizationService,
    canonicalize_category,
    normalize_merchant,
)
from .extraction_utils import parse_amount, parse_date
from .matching import DEFAULT_WINDOW_DAYS, MatchRow, find_duplicate

# (image_base64, content_type) -> {opening_balance, closing_balance, period,
# transactions: [...]}. Mirrors receipt_service.VisionFn but statement-shaped.
VisionFn = Callable[[str, str], dict]
# (raw_text) -> the same statement-shaped dict, for a pasted/typed blob.
TextLLMFn = Callable[[str], dict]


_STATEMENT_PROMPT = (
    "You are a bank-statement parser. Read this statement and respond with ONLY "
    "a JSON object, no prose:\n"
    '{"opening_balance": number, "closing_balance": number, '
    '"period": string, "transactions": [{"date": "YYYY-MM-DD", '
    '"description": string, "amount": number, "running_balance": number}]}\n'
    "Rules: 'amount' is SIGNED — positive for money IN (deposits/credits), "
    "negative for money OUT (withdrawals/debits). Use the running-balance column "
    "to decide the sign when the statement itself is ambiguous. "
    "'running_balance' is the account balance AFTER that line, or null if the "
    "statement has no running-balance column. Use null for any field you cannot read."
)


# ── Extraction dataclasses ──────────────────────────────────────────────────


@dataclass
class RawRow:
    """One line as the model reported it, pre-normalization (dollars)."""

    description: Optional[str]
    amount: Optional[float]  # signed dollars
    date: Optional[str]
    running_balance: Optional[float] = None


@dataclass
class StatementExtraction:
    """The model's view of a whole statement, pre-normalization (dollars)."""

    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    period: Optional[str] = None
    rows: list[RawRow] = field(default_factory=list)


# ── Normalized row (cents) ──────────────────────────────────────────────────


@dataclass
class NormRow:
    """A normalized, categorized, reconciled row in signed whole cents."""

    title: str
    amount_cents: int  # signed: +in / -out
    date: Optional[str]  # ISO YYYY-MM-DD or None if unparseable
    category: str = "Other"
    merchant_key: str = ""
    running_balance_cents: Optional[int] = None
    status: str = "ok"  # ok | duplicate | exception | needs_category | transfer_candidate
    reason: Optional[str] = None
    match_ref: Optional[int] = None


@dataclass
class ReconcileResult:
    """The balance-check headline, in cents."""

    opening_cents: Optional[int]
    closing_cents: Optional[int]
    expected_delta_cents: Optional[int]
    actual_delta_cents: int
    discrepancy_cents: Optional[int]
    reconciled: bool
    exception_count: int


def _default_vision_fn(image_b64: str, content_type: str) -> dict:
    """Call Groq's vision model for a statement. Lazy import so tests skip the SDK."""
    from groq import Groq

    from ..settings import settings

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=settings.groq_vision_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _STATEMENT_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{image_b64}"},
                    },
                ],
            }
        ],
    )
    return _loads_obj(response.choices[0].message.content)


def _default_text_llm_fn(raw_text: str) -> dict:
    """Call Groq's chat model to parse a pasted statement blob into JSON."""
    from groq import Groq

    from ..settings import settings

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=settings.groq_chat_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _STATEMENT_PROMPT},
            {"role": "user", "content": raw_text},
        ],
    )
    return _loads_obj(response.choices[0].message.content)


def _loads_obj(content: Optional[str]) -> dict:
    """Parse model output to a dict; empty dict on any non-object / bad JSON."""
    if not content:
        return {}
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class ReconciliationService:
    """Extract → normalize → categorize → dedup → reconcile → persist a session."""

    def __init__(
        self,
        db: Session,
        *,
        vision_fn: Optional[VisionFn] = None,
        text_llm_fn: Optional[TextLLMFn] = None,
        categorizer: Optional[CategorizationService] = None,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> None:
        self.db = db
        self.vision_fn = vision_fn or _default_vision_fn
        self.text_llm_fn = text_llm_fn or _default_text_llm_fn
        self.categorizer = categorizer or CategorizationService(db)
        self.window_days = window_days

    # ── Public entry ─────────────────────────────────────────────────────

    def ingest(
        self,
        *,
        user_id: int,
        account_id: int,
        source_kind: str,
        raw_bytes: Optional[bytes] = None,
        content_type: Optional[str] = None,
        raw_text: Optional[str] = None,
    ) -> ImportSessionORM:
        """Run the whole pipeline and persist a ``pending_review`` session.

        Raises ``ValueError`` if the account isn't the user's. May raise from the
        injected model call (the router maps that to a 502).
        """
        self._own_account(account_id, user_id)

        statement = self._extract(
            source_kind, raw_bytes=raw_bytes, content_type=content_type, raw_text=raw_text
        )
        rows = self._normalize(statement)
        self._categorize(user_id, rows)
        self._dedup(account_id, rows)
        recon = self._reconcile(statement, rows)
        return self._persist(user_id, account_id, source_kind, statement, rows, recon)

    # ── (a) extract ──────────────────────────────────────────────────────

    def _extract(
        self,
        source_kind: str,
        *,
        raw_bytes: Optional[bytes],
        content_type: Optional[str],
        raw_text: Optional[str],
    ) -> StatementExtraction:
        if source_kind in ("pdf", "image"):
            if raw_bytes is None:
                raise ValueError("image/pdf import needs bytes")
            image_b64 = base64.b64encode(raw_bytes).decode("ascii")
            raw = self.vision_fn(image_b64, content_type or "image/png") or {}
        elif source_kind == "text":
            if not raw_text:
                raise ValueError("text import needs raw_text")
            raw = self.text_llm_fn(raw_text) or {}
        else:
            raise ValueError(f"unsupported source_kind: {source_kind!r}")
        return self._to_extraction(raw)

    @staticmethod
    def _to_extraction(raw: dict) -> StatementExtraction:
        if not isinstance(raw, dict):
            raw = {}
        rows: list[RawRow] = []
        for item in raw.get("transactions") or []:
            if not isinstance(item, dict):
                continue
            rows.append(
                RawRow(
                    description=item.get("description"),
                    amount=parse_amount(item.get("amount")),
                    date=parse_date(item.get("date")),
                    running_balance=parse_amount(item.get("running_balance")),
                )
            )
        return StatementExtraction(
            opening_balance=parse_amount(raw.get("opening_balance")),
            closing_balance=parse_amount(raw.get("closing_balance")),
            period=(str(raw.get("period")).strip() if raw.get("period") else None),
            rows=rows,
        )

    # ── (b) normalize → cents ────────────────────────────────────────────

    def _normalize(self, statement: StatementExtraction) -> list[NormRow]:
        out: list[NormRow] = []
        for raw in statement.rows:
            title = (raw.description or "").strip()
            # A row missing an amount or date can't be trusted into the sum — it
            # surfaces as an exception rather than importing a guessed value.
            if raw.amount is None or raw.date is None or not title:
                out.append(
                    NormRow(
                        title=title or "(unreadable)",
                        amount_cents=dollars_to_cents(raw.amount) if raw.amount is not None else 0,
                        date=raw.date,
                        status="exception",
                        reason="missing_field",
                        merchant_key=normalize_merchant(title),
                    )
                )
                continue
            out.append(
                NormRow(
                    title=title,
                    amount_cents=dollars_to_cents(raw.amount),
                    date=raw.date,
                    merchant_key=normalize_merchant(title),
                    running_balance_cents=(
                        dollars_to_cents(raw.running_balance)
                        if raw.running_balance is not None
                        else None
                    ),
                )
            )
        return out

    # ── (c) categorize ───────────────────────────────────────────────────

    def _categorize(self, user_id: int, rows: list[NormRow]) -> None:
        # Only expense-side rows (money out) need a spend category; income keeps a
        # neutral label. Batch the unknowns through the existing categorizer.
        spend_titles = [r.title for r in rows if r.amount_cents < 0 and r.status != "exception"]
        cats = (
            self.categorizer.categorize_batch(user_id, spend_titles)
            if spend_titles
            else {}
        )
        for r in rows:
            if r.status == "exception":
                continue
            if r.amount_cents >= 0:
                r.category = "Transfer" if "transfer" in r.merchant_key else "Work"
                continue
            r.category = canonicalize_category(cats.get(r.title) or "Other")
            if r.category == "Other":
                r.status = "needs_category"
                r.reason = "uncategorized"

    # ── (d) dedup against existing rows (flag, never drop) ───────────────

    def _dedup(self, account_id: int, rows: list[NormRow]) -> None:
        # Dedup is scoped by account (already ownership-checked in ``ingest``).
        existing = self._existing_match_rows(account_id)
        if not existing:
            return
        for r in rows:
            if r.status == "exception" or r.date is None:
                continue
            candidate = MatchRow(
                ref=None,
                title=r.title,
                amount_cents=r.amount_cents,
                date=r.date,
                account_id=account_id,
            )
            hit = find_duplicate(candidate, existing, self.window_days)
            if hit is not None:
                r.status = "duplicate"
                r.reason = "matches_existing"
                ref = hit.ref  # opaque handle; here it is the existing txn id
                r.match_ref = ref if isinstance(ref, int) else None

    def _existing_match_rows(self, account_id: int) -> list[MatchRow]:
        """All current transactions on the account, as signed-cents MatchRows."""
        rows: list[MatchRow] = []
        expenses = self.db.execute(
            select(ExpenseORM).where(ExpenseORM.account_id == account_id)
        ).scalars()
        for e in expenses:
            rows.append(
                MatchRow(
                    ref=e.id,
                    title=e.title,
                    amount_cents=-abs(e.amount),  # expense = money out
                    date=e.date,
                    account_id=account_id,
                )
            )
        incomes = self.db.execute(
            select(IncomeORM).where(IncomeORM.account_id == account_id)
        ).scalars()
        for i in incomes:
            rows.append(
                MatchRow(
                    ref=i.id,
                    title=i.title,
                    amount_cents=abs(i.amount),  # income = money in
                    date=i.date,
                    account_id=account_id,
                )
            )
        return rows

    # ── (e) reconcile — the balance-check loop (pure cents) ──────────────

    def _reconcile(
        self, statement: StatementExtraction, rows: list[NormRow]
    ) -> ReconcileResult:
        opening = (
            dollars_to_cents(statement.opening_balance)
            if statement.opening_balance is not None
            else None
        )
        closing = (
            dollars_to_cents(statement.closing_balance)
            if statement.closing_balance is not None
            else None
        )

        # Per-row running-balance walk: localize the FIRST row whose running
        # balance can't be reached from the previous one. Only runs when the
        # statement actually carries a running-balance column and an opening.
        self._localize_running_balance(opening, rows)

        # The sum that the balance check is *about*: every row we'd import. A row
        # already flagged a duplicate is part of the statement's own sum, so it
        # still counts toward reconciliation — excluding it would make a correctly
        # extracted statement look unbalanced.
        actual_delta = sum(r.amount_cents for r in rows if r.status != "exception")

        expected_delta = (
            closing - opening if opening is not None and closing is not None else None
        )
        discrepancy = (
            expected_delta - actual_delta if expected_delta is not None else None
        )
        reconciled = discrepancy == 0
        exception_count = sum(1 for r in rows if r.status == "exception")

        return ReconcileResult(
            opening_cents=opening,
            closing_cents=closing,
            expected_delta_cents=expected_delta,
            actual_delta_cents=actual_delta,
            discrepancy_cents=discrepancy,
            reconciled=reconciled,
            exception_count=exception_count,
        )

    @staticmethod
    def _localize_running_balance(opening: Optional[int], rows: list[NormRow]) -> None:
        """Flag the first row that breaks the running-balance chain.

        Walk rows in given (statement) order: each row's stated running balance
        must equal the previous balance plus that row's signed amount. The first
        mismatch is where the extraction went wrong (a misread digit, a dropped
        row), so we flag exactly that row rather than only reporting a global gap.
        """
        if opening is None:
            return
        prev = opening
        for r in rows:
            if r.status == "exception" or r.running_balance_cents is None:
                # Can't chain through a row with no running balance; keep prev as
                # the last known good balance and continue.
                if r.status != "exception":
                    prev = prev + r.amount_cents
                continue
            if prev + r.amount_cents != r.running_balance_cents:
                r.status = "exception"
                r.reason = "running_balance_mismatch"
                # Re-anchor to the statement's stated balance so we don't cascade
                # one bad row into flagging every row after it.
                prev = r.running_balance_cents
            else:
                prev = r.running_balance_cents

    # ── persist ──────────────────────────────────────────────────────────

    def _persist(
        self,
        user_id: int,
        account_id: int,
        source_kind: str,
        statement: StatementExtraction,
        rows: list[NormRow],
        recon: ReconcileResult,
    ) -> ImportSessionORM:
        session = ImportSessionORM(
            user_id=user_id,
            account_id=account_id,
            source_kind=source_kind,
            status="pending_review",
            opening_balance=recon.opening_cents,
            closing_balance=recon.closing_cents,
            statement_period=statement.period,
            reconciled=1 if recon.reconciled else 0,
            discrepancy_cents=recon.discrepancy_cents or 0,
        )
        self.db.add(session)
        self.db.flush()  # session.id

        for r in rows:
            self.db.add(
                ImportRowORM(
                    session_id=session.id,
                    title=r.title,
                    amount=r.amount_cents,
                    date=r.date or "",
                    category=r.category,
                    merchant_key=r.merchant_key,
                    running_balance=r.running_balance_cents,
                    status=r.status,
                    reason=r.reason,
                    # Clean rows default to included; exceptions and duplicates
                    # start excluded so the user opts them in deliberately.
                    included=0 if r.status in ("exception", "duplicate") else 1,
                    match_ref=r.match_ref,
                )
            )
        self.db.flush()
        return session

    # ── commit (called from the confirm endpoint via ActionService) ──────

    def commit_session(self, user_id: int, session_id: int) -> dict:
        """Turn the session's included, non-duplicate rows into transactions.

        Idempotent and atomic per the caller's transaction: each created row
        carries its ``import_row_id``, whose partial unique index makes a replay
        a no-op rather than a double-insert. A row already flagged a duplicate or
        an exception is skipped unless the user explicitly re-included it. Raises
        ``ValueError`` if the session isn't the user's or isn't pending review.
        """
        from .transaction_service import TransactionService

        session = self.db.get(ImportSessionORM, session_id)
        if session is None or session.user_id != user_id:
            raise ValueError("import session not found")
        if session.status != "pending_review":
            raise ValueError("import session is not pending review")

        tx_svc = TransactionService(self.db)
        rows = self.db.execute(
            select(ImportRowORM).where(ImportRowORM.session_id == session.id)
        ).scalars().all()

        committed = 0
        for r in rows:
            if not r.included or r.status == "exception":
                continue
            is_income = r.amount > 0
            model = IncomeORM if is_income else ExpenseORM
            sign = 1 if is_income else -1
            tx_svc.create(
                user_id,
                model,
                sign,
                title=r.title,
                amount=abs(r.amount) / 100.0,  # service takes dollars; row is cents
                tx_date=r.date,
                category=r.category or ("Income" if is_income else ""),
                account_id=session.account_id,
                extra_fields={"import_row_id": r.id},
            )
            # Re-read the created row by its unique import_row_id to record the link.
            created = self.db.execute(
                select(model).where(model.import_row_id == r.id)
            ).scalar_one()
            if is_income:
                r.committed_income_id = created.id
            else:
                r.committed_expense_id = created.id
            committed += 1

        session.status = "committed"
        session.committed_at = func.now()
        self.db.flush()
        return {"committed": committed, "session_id": session.id}

    # ── review payload (cents → dollars at the API boundary) ─────────────

    def review_payload(self, user_id: int, session_id: int) -> dict:
        """Build the dollar-denominated review payload for a session.

        Returns a dict matching ``models.ImportSessionOut``. Raises ``ValueError``
        if the session isn't the user's. Recomputes the balance check from the
        persisted rows so it stays correct after the user edits a row.
        """
        from ..money import cents_to_dollars

        session = self.db.get(ImportSessionORM, session_id)
        if session is None or session.user_id != user_id:
            raise ValueError("import session not found")

        rows = self.db.execute(
            select(ImportRowORM)
            .where(ImportRowORM.session_id == session.id)
            .order_by(ImportRowORM.id)
        ).scalars().all()

        actual_delta = sum(r.amount for r in rows if r.status != "exception")
        exception_count = sum(1 for r in rows if r.status == "exception")
        opening = session.opening_balance
        closing = session.closing_balance
        expected_delta = (
            closing - opening if opening is not None and closing is not None else None
        )
        discrepancy = (
            expected_delta - actual_delta if expected_delta is not None else None
        )

        def _d(cents: Optional[int]) -> Optional[float]:
            return cents_to_dollars(cents) if cents is not None else None

        return {
            "id": session.id,
            "account_id": session.account_id,
            "source_kind": session.source_kind,
            "status": session.status,
            "statement_period": session.statement_period,
            "balance_check": {
                "opening": _d(opening),
                "closing": _d(closing),
                "expected_delta": _d(expected_delta),
                "actual_delta": cents_to_dollars(actual_delta),
                "discrepancy": _d(discrepancy),
                "reconciled": discrepancy == 0,
                "exception_count": exception_count,
            },
            "rows": [
                {
                    "id": r.id,
                    "title": r.title,
                    "amount": cents_to_dollars(r.amount),
                    "date": r.date,
                    "category": r.category,
                    "running_balance": _d(r.running_balance),
                    "status": r.status,
                    "reason": r.reason,
                    "included": bool(r.included),
                    "match_ref": r.match_ref,
                }
                for r in rows
            ],
        }

    def patch_row(
        self,
        user_id: int,
        session_id: int,
        row_id: int,
        *,
        title: Optional[str] = None,
        amount_dollars: Optional[float] = None,
        date: Optional[str] = None,
        category: Optional[str] = None,
        included: Optional[bool] = None,
    ) -> dict:
        """Apply a user edit to one row, then re-check the balance.

        Editing an amount/date can flip a previously-flagged row back to ``ok``
        (the user fixed a misread), so an edited row that was an exception is
        re-cleared. Returns the refreshed review payload.
        """
        session = self.db.get(ImportSessionORM, session_id)
        if session is None or session.user_id != user_id:
            raise ValueError("import session not found")
        if session.status != "pending_review":
            raise ValueError("import session is not pending review")

        row = self.db.get(ImportRowORM, row_id)
        if row is None or row.session_id != session.id:
            raise ValueError("import row not found")

        if title is not None:
            row.title = title
            row.merchant_key = normalize_merchant(title)
        if amount_dollars is not None:
            row.amount = dollars_to_cents(amount_dollars)
        if date is not None:
            row.date = date
        if category is not None:
            row.category = canonicalize_category(category)
        if included is not None:
            row.included = 1 if included else 0
        # A user edit to the substance of a flagged row clears the flag — they've
        # taken responsibility for the value.
        if (
            row.status in ("exception", "needs_category")
            and any(v is not None for v in (title, amount_dollars, date, category))
        ):
            row.status = "ok"
            row.reason = None

        self.db.flush()
        return self.review_payload(user_id, session_id)

    def discard_session(self, user_id: int, session_id: int) -> None:
        session = self.db.get(ImportSessionORM, session_id)
        if session is None or session.user_id != user_id:
            raise ValueError("import session not found")
        session.status = "discarded"
        self.db.flush()

    # ── helpers ──────────────────────────────────────────────────────────

    def _own_account(self, account_id: int, user_id: int) -> AccountORM:
        account = self.db.get(AccountORM, account_id)
        if account is None or account.user_id != user_id:
            raise ValueError("account not found")
        return account
