"""Schedule-C tax-bucket registry (code, not DB).

Mirrors ``CANONICAL_CATEGORIES`` / ``PLAID_PFC_TO_CANONICAL`` in
``categorization_service.py``: a frozen, code-owned taxonomy with a
``canonicalize_bucket`` resolver that maps near-misses onto a real key or
rejects — it NEVER mints a ghost bucket (the same discipline that keeps a typo'd
spend category from silently creating a new column of truth).

The tax bucket is ORTHOGONAL to the 12 spend categories: a $60 "Staples" charge
is spend-category ``Shops`` AND (optionally) tax-bucket ``sch_c_18_office``.
Different tables, different code paths — they never collide.

``deductible_bps`` (basis points, 0–10000) lets a bucket carry its default
deductible fraction exactly in cents: 50% meals = 5000, 100% office = 10000.
Home-office is a per-user percentage so its default is 10000 and the user/agent
overrides the bps at tag time.

US calendar-year filer, Schedule C (sole proprietor) framing. This ORGANIZES;
it never asserts eligibility.
"""

from __future__ import annotations

import re
from typing import Optional, TypedDict


class BucketSpec(TypedDict):
    label: str  # human label, including the IRS line, e.g. "Office (Sch C line 18)"
    irs_line: str  # the Schedule-C line reference, for the summary engine
    default_deductible_bps: int  # 0–10000; the bucket's default deductible fraction
    kind: str  # 'expense' | 'income' — which ledger axis the bucket applies to


# ── the frozen registry ──────────────────────────────────────────────────────
# Expense buckets follow the IRS Schedule C Part II line numbers. Meals default
# to 50% (5000 bps) per the standard limitation; everything else defaults to
# 100% and the user/agent narrows it. Income keys document 1099 sources for the
# summary's income-by-source breakdown (orthogonal to deductibility).
TAX_BUCKETS: dict[str, BucketSpec] = {
    # ── Schedule C Part II — deductible business expenses ──
    "sch_c_8_advertising": {
        "label": "Advertising (Sch C line 8)",
        "irs_line": "Schedule C line 8",
        "default_deductible_bps": 10000,
        "kind": "expense",
    },
    "sch_c_9_car_truck": {
        "label": "Car & truck (Sch C line 9)",
        "irs_line": "Schedule C line 9",
        "default_deductible_bps": 10000,
        "kind": "expense",
    },
    "sch_c_18_office": {
        "label": "Office expense (Sch C line 18)",
        "irs_line": "Schedule C line 18",
        "default_deductible_bps": 10000,
        "kind": "expense",
    },
    "sch_c_22_supplies": {
        "label": "Supplies (Sch C line 22)",
        "irs_line": "Schedule C line 22",
        "default_deductible_bps": 10000,
        "kind": "expense",
    },
    "sch_c_24a_travel": {
        "label": "Travel (Sch C line 24a)",
        "irs_line": "Schedule C line 24a",
        "default_deductible_bps": 10000,
        "kind": "expense",
    },
    "sch_c_24b_meals": {
        "label": "Meals (Sch C line 24b)",
        "irs_line": "Schedule C line 24b",
        "default_deductible_bps": 5000,  # standard 50% meals limitation
        "kind": "expense",
    },
    "sch_c_27a_other": {
        "label": "Other expenses (Sch C line 27a)",
        "irs_line": "Schedule C line 27a",
        "default_deductible_bps": 10000,
        "kind": "expense",
    },
    "sch_c_30_home_office": {
        "label": "Home office (Sch C line 30)",
        "irs_line": "Schedule C line 30",
        # The business-use % is per-user; default to 100% and let the user/agent
        # set the actual bps at tag time (the summary applies it exactly in cents).
        "default_deductible_bps": 10000,
        "kind": "expense",
    },
    # ── 1099 income sources (organization only; deductibility N/A) ──
    "income_1099_nec": {
        "label": "1099-NEC nonemployee compensation",
        "irs_line": "Schedule C line 1 (1099-NEC)",
        "default_deductible_bps": 0,
        "kind": "income",
    },
    "income_1099_misc": {
        "label": "1099-MISC income",
        "irs_line": "Schedule C / Schedule 1 (1099-MISC)",
        "default_deductible_bps": 0,
        "kind": "income",
    },
    "income_1099_k": {
        "label": "1099-K payment-card / third-party network income",
        "irs_line": "Schedule C line 1 (1099-K)",
        "default_deductible_bps": 0,
        "kind": "income",
    },
}

# Frozen set of valid keys — the single source of truth for "is this a real
# bucket?". Mirrors ``CANONICAL_CATEGORIES``.
VALID_BUCKETS: frozenset[str] = frozenset(TAX_BUCKETS)

# ── keyword map for the 2-tier suggester (learned → keyword; no Groq tier) ────
# Longer keywords win (same convention as ``rule_category``). Deliberately
# conservative: a miss returns None and the user/agent tags explicitly. These
# are merchant/title hints, NOT eligibility assertions.
_BUCKET_KEYWORDS: dict[str, str] = {
    "staples": "sch_c_18_office",
    "office depot": "sch_c_18_office",
    "officemax": "sch_c_18_office",
    "fedex office": "sch_c_18_office",
    "uline": "sch_c_22_supplies",
    "facebook ads": "sch_c_8_advertising",
    "google ads": "sch_c_8_advertising",
    "linkedin ads": "sch_c_8_advertising",
    "uber": "sch_c_9_car_truck",
    "lyft": "sch_c_9_car_truck",
    "shell": "sch_c_9_car_truck",
    "chevron": "sch_c_9_car_truck",
    "delta air": "sch_c_24a_travel",
    "united airlines": "sch_c_24a_travel",
    "marriott": "sch_c_24a_travel",
    "hilton": "sch_c_24a_travel",
    "airbnb": "sch_c_24a_travel",
}


def _norm(s: str) -> str:
    """Lower, strip punctuation/digits, collapse whitespace — mirrors
    ``normalize_merchant`` so the keyword map sees a stable key."""
    text = (s or "").lower()
    text = re.sub(r"[0-9]+", " ", text)
    text = re.sub(r"[^a-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_bucket(raw: Optional[str]) -> Optional[str]:
    """Resolve a raw bucket label onto a real registry key, or ``None``.

    Resolution order (mirrors ``canonicalize_category`` but REJECTS instead of
    preserving — a ghost tax bucket would silently corrupt the summary):
    1. An exact key (``"sch_c_18_office"``).
    2. A case/space/underscore-insensitive match of a key.
    3. A case-insensitive match of a bucket's human label or IRS line.
    Anything else → ``None`` (caller raises a validation error). Never mints a
    new key.

    >>> canonicalize_bucket("sch_c_18_office")
    'sch_c_18_office'
    >>> canonicalize_bucket("SCH C 18 OFFICE")
    'sch_c_18_office'
    >>> canonicalize_bucket("Office expense (Sch C line 18)")
    'sch_c_18_office'
    >>> canonicalize_bucket("not a bucket") is None
    True
    """
    if not raw or not raw.strip():
        return None
    s = raw.strip()
    if s in VALID_BUCKETS:
        return s
    norm = re.sub(r"[_\s]+", "_", s.lower()).strip("_")
    if norm in VALID_BUCKETS:
        return norm
    # label / irs_line match
    low = s.lower()
    for key, spec in TAX_BUCKETS.items():
        if low == spec["label"].lower() or low == spec["irs_line"].lower():
            return key
    return None


def suggest_bucket(title: str) -> Optional[str]:
    """Keyword-tier bucket suggestion for a transaction title, or ``None``.

    Longer keywords are tried first ("fedex office" beats nothing here, but the
    convention matches ``rule_category``). A miss returns ``None`` — the suggester
    never guesses a bucket it isn't reasonably sure of; the agent's propose tool
    (LLM path, always behind confirm) covers the rest.
    """
    key = _norm(title)
    if not key:
        return None
    for keyword in sorted(_BUCKET_KEYWORDS, key=len, reverse=True):
        if keyword in key:
            return _BUCKET_KEYWORDS[keyword]
    return None


def bucket_label(bucket: str) -> str:
    """Human label for a bucket key (factual register the firewall accepts).

    Falls back to the bare key if somehow unknown (defensive; callers should
    have canonicalized first).
    """
    spec = TAX_BUCKETS.get(bucket)
    return spec["label"] if spec else bucket


def default_deductible_bps(bucket: str) -> int:
    """The bucket's default deductible fraction in basis points (0 if unknown)."""
    spec = TAX_BUCKETS.get(bucket)
    return spec["default_deductible_bps"] if spec else 0
