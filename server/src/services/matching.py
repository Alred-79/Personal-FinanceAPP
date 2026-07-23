"""Fuzzy transaction matching — the shared core of import dedup and detangling.

Two features lean on the same primitive:

* **Reconciliation Desk** (``reconciliation_service``) asks "is this parsed
  statement row the *same* transaction as one I already have?" so it can flag a
  duplicate instead of double-importing it.
* **The Detangler** (``detangle_service``) asks "are these two existing
  transactions a transfer between the user's own accounts, a refund of an
  earlier purchase, or an accidental duplicate?" so it can offer to collapse or
  link them.

Both reduce to comparing a normalized merchant key, an amount in whole cents,
and a date that falls inside a small window. This module holds that comparison
and nothing else: it is **pure** (no DB, no network, no clock) so it unit-tests
as a truth table. Everything money is integer cents — never float — so equality
is exact and the reconcile math downstream can trust it.

Merchant keys come from ``normalize_merchant`` in ``categorization_service`` so
the dedup view of "same merchant" matches the categorizer's, rather than drifting
into a second, subtly different notion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

from .categorization_service import normalize_merchant

# How many days apart two rows may sit and still be considered the same event /
# a related pair. Bank "date" can differ between the merchant's clock, the
# authorization, and the posting, so an exact-day match is too strict; a few
# days is the usual spread. Callers may override per call (e.g. transfers post
# faster than refunds settle).
DEFAULT_WINDOW_DAYS = 3


def _to_date(value: str | date | datetime) -> Optional[date]:
    """Coerce an ISO string / date / datetime to a ``date``; None if unparseable.

    Transaction dates are stored as ISO ``YYYY-MM-DD`` strings (see
    ``Expense.date``), but callers may already hold a ``date``. Anything we can't
    read yields None so a single malformed date can't crash a whole batch — the
    row simply won't match by date and surfaces for review.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class MatchRow:
    """The minimal view of a transaction the matcher needs.

    Built from either a parsed import row or an existing ``Expense``/``Income``.
    ``amount_cents`` is **signed**: positive = money in (income/credit), negative
    = money out (expense/debit). This mirrors Plaid's own sign convention used in
    ``plaid_service`` and is what lets us spot a transfer (equal magnitude,
    opposite sign) or a refund (a credit answering an earlier debit).
    """

    ref: object  # opaque caller handle (a row id, an ORM object, an index)
    title: str
    amount_cents: int  # signed: +in / -out
    date: str | date | datetime
    account_id: Optional[int] = None
    category: str = ""

    @property
    def merchant_key(self) -> str:
        return normalize_merchant(self.title)

    @property
    def magnitude(self) -> int:
        return abs(self.amount_cents)


def within_window(a: MatchRow, b: MatchRow, window_days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """True if *a* and *b* are dated within ``window_days`` of each other.

    A row with an unparseable date never falls inside any window — it can't be
    silently matched, so it surfaces for human review instead.
    """
    da, db = _to_date(a.date), _to_date(b.date)
    if da is None or db is None:
        return False
    return abs((da - db).days) <= window_days


def is_duplicate(a: MatchRow, b: MatchRow, window_days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """Same merchant, same signed amount, close in time → the same transaction.

    This is the dedup question: a statement row that re-states a transaction the
    user already has (via Plaid sync or an earlier import). Sign must match —
    a +$40 refund is *not* a duplicate of a -$40 purchase (that's a refund pair).
    """
    if a.amount_cents != b.amount_cents:
        return False
    ka, kb = a.merchant_key, b.merchant_key
    if not ka or ka != kb:
        return False
    return within_window(a, b, window_days)


def is_transfer_pair(a: MatchRow, b: MatchRow, window_days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """Equal magnitude, opposite sign, *different* accounts, close in time.

    A transfer is money the user moved between their own accounts: it leaves one
    (-X) and lands in another (+X). Counted naively it looks like a big expense
    *and* a big income, polluting spend totals — so the Detangler offers to
    collapse the pair. Requires both account ids and that they differ, so a
    refund inside one account is never mistaken for a transfer.
    """
    if a.account_id is None or b.account_id is None:
        return False
    if a.account_id == b.account_id:
        return False
    if a.amount_cents != -b.amount_cents:  # equal magnitude, opposite sign
        return False
    if a.amount_cents == 0:
        return False
    if not within_window(a, b, window_days):
        return False
    return _has_explicit_transfer_marker(a) or _has_explicit_transfer_marker(b)


_TRANSFER_MARKERS = (
    "transfer",
    "xfer",
    "own account",
    "account to account",
    "ach transfer",
)
_PURCHASE_MARKERS = ("purchase", "point of sale", "pos debit", "card purchase")
_REFUND_MARKERS = ("refund", "reversal", "reversed", "returned item")


def _has_explicit_transfer_marker(row: MatchRow) -> bool:
    """True only when title/category explicitly describes a money transfer."""
    text = f"{row.title} {row.category}".strip().lower()
    if any(marker in text for marker in _PURCHASE_MARKERS):
        return False
    return any(marker in text for marker in _TRANSFER_MARKERS)


def _has_explicit_refund_marker(row: MatchRow) -> bool:
    text = f"{row.title} {row.category}".strip().lower()
    return any(marker in text for marker in _REFUND_MARKERS)


def is_refund_pair(a: MatchRow, b: MatchRow, window_days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """A credit answering an earlier debit at the *same merchant*.

    Opposite sign, equal magnitude, same merchant key, close in time. Unlike a
    transfer this lives within one merchant relationship rather than between two
    of the user's accounts, so the merchant key must match and we do *not*
    require differing accounts (a refund usually returns to the same card).
    """
    ka, kb = a.merchant_key, b.merchant_key
    if not ka or ka != kb:
        return False
    if a.amount_cents != -b.amount_cents:
        return False
    if a.amount_cents == 0:
        return False
    return within_window(a, b, window_days)


def find_duplicate(
    row: MatchRow,
    existing: Iterable[MatchRow],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Optional[MatchRow]:
    """First existing row that is a duplicate of *row*, else None.

    Used by import dedup: for each parsed statement row, scan the account's
    current transactions and return the one it duplicates so the caller can flag
    it (``status="duplicate"``, ``match_ref=<id>``) — never auto-drop, because a
    false positive silently loses a real transaction and breaks the balance check.
    """
    for candidate in existing:
        if is_duplicate(row, candidate, window_days):
            return candidate
    return None


@dataclass(frozen=True)
class Pairing:
    """A detected relationship between two existing transactions."""

    kind: str  # 'transfer' | 'refund' | 'duplicate'
    a: MatchRow
    b: MatchRow


def find_pairings(
    rows: list[MatchRow],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[Pairing]:
    """Detect transfer / refund / duplicate pairs within one set of rows.

    The Detangler's workhorse. Each unordered pair is considered once. A pair is
    classified at most once, strongest evidence first: an explicit refund marker
    beats a transfer marker; otherwise a conservatively marked transfer beats
    same-merchant refund inference, then a plain duplicate. Each row participates in at most one pairing so a single
    transaction can't be claimed by two conflicting suggestions.
    """
    pairings: list[Pairing] = []
    claimed: set[int] = set()
    for i in range(len(rows)):
        if i in claimed:
            continue
        for j in range(i + 1, len(rows)):
            if j in claimed:
                continue
            a, b = rows[i], rows[j]
            kind: Optional[str] = None
            transfer = is_transfer_pair(a, b, window_days)
            refund = is_refund_pair(a, b, window_days)
            if refund and (
                _has_explicit_refund_marker(a) or _has_explicit_refund_marker(b)
            ):
                kind = "refund"
            elif transfer:
                kind = "transfer"
            elif refund:
                kind = "refund"
            elif is_duplicate(a, b, window_days):
                kind = "duplicate"
            if kind:
                pairings.append(Pairing(kind=kind, a=a, b=b))
                claimed.add(i)
                claimed.add(j)
                break  # row i is spent; move to the next unclaimed row
    return pairings
