"""Fuzzy matcher truth tables — pure, no DB.

Covers the four questions ``matching`` answers (duplicate / transfer / refund /
pairings) plus the two parse helpers in ``extraction_utils`` they lean on. Money
is always whole signed cents so equality is exact.
"""

from server.src.services.extraction_utils import parse_amount, parse_date
from server.src.services.matching import (
    MatchRow,
    find_duplicate,
    find_pairings,
    is_duplicate,
    is_refund_pair,
    is_transfer_pair,
    within_window,
)


def _row(ref, title, cents, date, account_id=None):
    return MatchRow(
        ref=ref, title=title, amount_cents=cents, date=date, account_id=account_id
    )


# ── extraction_utils.parse_amount ───────────────────────────────────────────

def test_parse_amount_strips_currency_and_separators():
    assert parse_amount("$1,234.50") == 1234.5
    assert parse_amount("1234.5") == 1234.5
    assert parse_amount(42) == 42.0
    assert parse_amount(-3.005) == -3.0  # rounds to 2dp


def test_parse_amount_none_and_garbage():
    assert parse_amount(None) is None
    assert parse_amount("") is None
    assert parse_amount("n/a") is None
    assert parse_amount("-") is None
    assert parse_amount(True) is None  # bool is not an amount


def test_parse_date_formats():
    assert parse_date("2026-03-14") == "2026-03-14"
    assert parse_date("03/14/2026") == "2026-03-14"
    assert parse_date("March 14, 2026") == "2026-03-14"
    assert parse_date("14 Mar 2026") == "2026-03-14"


def test_parse_date_garbage_is_none():
    assert parse_date("garbage") is None
    assert parse_date(None) is None
    assert parse_date("") is None


# ── within_window ───────────────────────────────────────────────────────────

def test_within_window_inclusive_and_unparseable():
    a = _row(1, "X", -100, "2026-03-10")
    b = _row(2, "X", -100, "2026-03-13")
    assert within_window(a, b, window_days=3) is True
    assert within_window(a, b, window_days=2) is False
    bad = _row(3, "X", -100, "not-a-date")
    assert within_window(a, bad) is False  # unparseable never matches


# ── is_duplicate ────────────────────────────────────────────────────────────

def test_duplicate_same_merchant_amount_close_date():
    a = _row(1, "NETFLIX.COM #1234", -1599, "2026-03-01")
    b = _row(2, "Netflix.com 5678", -1599, "2026-03-02")
    assert is_duplicate(a, b) is True


def test_duplicate_requires_matching_sign():
    purchase = _row(1, "Amazon", -4000, "2026-03-01")
    refund = _row(2, "Amazon", 4000, "2026-03-01")
    assert is_duplicate(purchase, refund) is False  # that's a refund, not a dup


def test_duplicate_blank_merchant_never_matches():
    a = _row(1, "   ", -100, "2026-03-01")
    b = _row(2, "!!!", -100, "2026-03-01")  # normalizes to empty key
    assert is_duplicate(a, b) is False


# ── is_transfer_pair ────────────────────────────────────────────────────────

def test_transfer_opposite_sign_cross_account():
    out_ = _row(1, "Transfer to Savings", -50000, "2026-03-01", account_id=1)
    in_ = _row(2, "Transfer from Checking", 50000, "2026-03-01", account_id=2)
    assert is_transfer_pair(out_, in_) is True


def test_transfer_requires_two_distinct_accounts():
    out_ = _row(1, "move", -50000, "2026-03-01", account_id=1)
    in_same = _row(2, "move", 50000, "2026-03-01", account_id=1)
    assert is_transfer_pair(out_, in_same) is False  # same account → not a transfer
    in_noacct = _row(3, "move", 50000, "2026-03-01", account_id=None)
    assert is_transfer_pair(out_, in_noacct) is False  # missing account


def test_transfer_rejects_zero_and_unequal_magnitude():
    a = _row(1, "x", 0, "2026-03-01", account_id=1)
    b = _row(2, "x", 0, "2026-03-01", account_id=2)
    assert is_transfer_pair(a, b) is False
    c = _row(3, "x", -100, "2026-03-01", account_id=1)
    d = _row(4, "x", 200, "2026-03-01", account_id=2)
    assert is_transfer_pair(c, d) is False


# ── is_refund_pair ──────────────────────────────────────────────────────────

def test_refund_same_merchant_opposite_sign():
    # Both titles normalize to the same merchant key "amazon" (digits/punct
    # stripped); the ".com" suffix would split the key, so it's omitted here —
    # exactly the shared-key notion normalize_merchant enforces.
    purchase = _row(1, "AMAZON #999", -4000, "2026-03-01")
    refund = _row(2, "Amazon", 4000, "2026-03-03")  # within the default 3-day window
    assert is_refund_pair(purchase, refund) is True
    # Refunds often settle slowly; a wider explicit window still pairs them.
    slow_refund = _row(3, "Amazon", 4000, "2026-03-12")
    assert is_refund_pair(purchase, slow_refund) is False  # outside default
    assert is_refund_pair(purchase, slow_refund, window_days=14) is True


def test_refund_different_merchant_is_not_a_refund():
    purchase = _row(1, "Amazon", -4000, "2026-03-01")
    credit = _row(2, "Target", 4000, "2026-03-02")
    assert is_refund_pair(purchase, credit) is False


# ── find_duplicate ──────────────────────────────────────────────────────────

def test_find_duplicate_returns_first_match():
    row = _row("new", "Starbucks #5", -650, "2026-03-10")
    existing = [
        _row("a", "Whole Foods", -2200, "2026-03-09"),
        _row("b", "STARBUCKS 0012", -650, "2026-03-11"),  # the dup
        _row("c", "Starbucks", -650, "2026-03-10"),
    ]
    hit = find_duplicate(row, existing)
    assert hit is not None and hit.ref == "b"


def test_find_duplicate_none_when_absent():
    row = _row("new", "Starbucks", -650, "2026-03-10")
    existing = [_row("a", "Whole Foods", -2200, "2026-03-09")]
    assert find_duplicate(row, existing) is None


# ── find_pairings ───────────────────────────────────────────────────────────

def test_find_pairings_classifies_and_claims_each_row_once():
    rows = [
        _row(1, "Transfer", -50000, "2026-03-01", account_id=1),
        _row(2, "Transfer", 50000, "2026-03-01", account_id=2),
        _row(3, "Amazon", -4000, "2026-03-02", account_id=1),
        _row(4, "Amazon", 4000, "2026-03-04", account_id=1),  # refund of 3
        _row(5, "Rent", -120000, "2026-03-05", account_id=1),  # unpaired
    ]
    pairings = find_pairings(rows)
    kinds = sorted(p.kind for p in pairings)
    assert kinds == ["refund", "transfer"]
    transfer = next(p for p in pairings if p.kind == "transfer")
    assert {transfer.a.ref, transfer.b.ref} == {1, 2}
    refund = next(p for p in pairings if p.kind == "refund")
    assert {refund.a.ref, refund.b.ref} == {3, 4}


def test_find_pairings_prefers_transfer_over_refund():
    # Same merchant AND cross-account opposite-sign → transfer wins (more specific).
    rows = [
        _row(1, "Acme Bank", -30000, "2026-03-01", account_id=1),
        _row(2, "Acme Bank", 30000, "2026-03-01", account_id=2),
    ]
    pairings = find_pairings(rows)
    assert len(pairings) == 1
    assert pairings[0].kind == "transfer"


def test_find_pairings_empty_when_nothing_relates():
    rows = [
        _row(1, "Rent", -120000, "2026-03-01", account_id=1),
        _row(2, "Salary", 300000, "2026-03-02", account_id=1),
    ]
    assert find_pairings(rows) == []
