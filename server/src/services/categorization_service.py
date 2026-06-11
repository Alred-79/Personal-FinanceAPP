"""Service that picks a category on its own.

Resolves a transaction's category in three tiers, most trusted first:

1. **Learned mapping**: a ``MerchantCategory`` row for that user, set by a manual
   rename or an earlier Groq result. This is what makes user renames stick.
2. **Keyword rules**: a small built in substring map (``uber`` goes to Transport).
3. **Groq fallback**: an LLM call for merchants we don't know yet. The call comes
   in as ``llm_fn`` so it stays cheap (batched, text only) and is easy to mock in
   tests. Results are saved as learned mappings so we never pay for the same one twice.

The pure helpers (``normalize_merchant``, ``rule_category``) touch neither the DB
nor the network and have their own unit tests.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import MerchantCategory as MerchantCategoryORM

# A type alias for the Groq call: maps a list of merchant titles → {title: category}.
LLMFn = Callable[[list[str]], dict[str, str]]

DEFAULT_CATEGORY = "Other"

# The keyword to category rules built in. Keys are matched ignoring case as
# substrings of the *normalized* merchant.  Categories use the same labels as
# the frontend palette (``client/src/store/useStore.ts``).
KEYWORD_RULES: dict[str, str] = {
    "uber": "Transportation",
    "lyft": "Transportation",
    "shell": "Transportation",
    "exxon": "Transportation",
    "chevron": "Transportation",
    "delta air": "Travel",
    "airbnb": "Travel",
    "marriott": "Travel",
    "hotel": "Travel",
    "netflix": "Entertainment",
    "spotify": "Entertainment",
    "hulu": "Entertainment",
    "disney": "Entertainment",
    "hbo": "Entertainment",
    "steam games": "Entertainment",
    "starbucks": "Food and Drink",
    "mcdonald": "Food and Drink",
    "chipotle": "Food and Drink",
    "doordash": "Food and Drink",
    "grubhub": "Food and Drink",
    "uber eats": "Food and Drink",
    "amazon": "Shops",
    "walmart": "Shops",
    "target": "Shops",
    "costco": "Shops",
    "comcast": "Utilities",
    "verizon": "Utilities",
    "at t": "Utilities",
    "t mobile": "Utilities",
    "pg e": "Utilities",
    "rent": "Housing",
    "mortgage": "Housing",
}

# Canonical category labels. These mirror the frontend palette keys in
# ``client/src/lib/colors.ts``; budgets, charts, and the color map all key off
# these exact strings. Anything we store should be one of these, or a user's
# own custom label (which ``canonicalize_category`` preserves verbatim).
CANONICAL_CATEGORIES: tuple[str, ...] = (
    "Housing",
    "Food",
    "Transportation",
    "Utilities",
    "Entertainment",
    "Work",
    "Food and Drink",
    "Service",
    "Shops",
    "Transfer",
    "Travel",
    "Other",
)

# Plaid Personal Finance Category "primary" codes (UPPER_SNAKE) → our labels.
# Plaid's PFC primary is a fixed enum; map each to the nearest canonical label.
# Anything not listed falls through to a case/spacing-insensitive match and,
# failing that, is kept as-is (see ``canonicalize_category``).
PLAID_PFC_TO_CANONICAL: dict[str, str] = {
    "INCOME": "Work",
    "TRANSFER_IN": "Transfer",
    "TRANSFER_OUT": "Transfer",
    "LOAN_PAYMENTS": "Housing",
    "BANK_FEES": "Service",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Food and Drink",
    "GENERAL_MERCHANDISE": "Shops",
    "HOME_IMPROVEMENT": "Housing",
    "MEDICAL": "Service",
    "PERSONAL_CARE": "Service",
    "GENERAL_SERVICES": "Service",
    "GOVERNMENT_AND_NON_PROFIT": "Service",
    "TRANSPORTATION": "Transportation",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Utilities",
}

_CANONICAL_BY_LOWER = {c.lower(): c for c in CANONICAL_CATEGORIES}


def canonicalize_category(raw: str | None) -> str:
    """Map a raw category label onto the app's canonical taxonomy.

    Resolution order:
    1. A Plaid PFC primary code (e.g. ``"FOOD_AND_DRINK"``, or the spaced form
       ``"Food and Drink"``) → its mapped canonical label.
    2. A label matching a canonical name ignoring case/spacing/underscores
       (e.g. ``"transportation"`` → ``"Transportation"``).
    3. Anything else is a user's own custom label and is preserved verbatim, so
       their matching budgets keep working. Empty/blank → the default category.

    >>> canonicalize_category("FOOD_AND_DRINK")
    'Food and Drink'
    >>> canonicalize_category("transportation")
    'Transportation'
    >>> canonicalize_category("Pets")
    'Pets'
    >>> canonicalize_category("")
    'Other'
    """
    if not raw or not raw.strip():
        return DEFAULT_CATEGORY
    s = raw.strip()
    code = re.sub(r"\s+", "_", s.upper())
    if code in PLAID_PFC_TO_CANONICAL:
        return PLAID_PFC_TO_CANONICAL[code]
    norm = re.sub(r"[_\s]+", " ", s).strip().lower()
    if norm in _CANONICAL_BY_LOWER:
        return _CANONICAL_BY_LOWER[norm]
    return s


def normalize_merchant(title: str) -> str:
    """Reduce a raw transaction title to a stable merchant key.

    Lowercases, drops digits (store/location numbers) and punctuation, and
    collapses whitespace so ``"NETFLIX.COM #1234"`` and ``"Netflix.com 5678"``
    map to the same key ``"netflix com"``.

    >>> normalize_merchant("NETFLIX.COM #1234")
    'netflix com'
    >>> normalize_merchant("  ")
    ''
    """
    if not title:
        return ""
    text = title.lower()
    text = re.sub(r"[0-9]+", " ", text)  # strip digits
    text = re.sub(r"[^a-z\s]", " ", text)  # strip punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


def rule_category(title: str) -> Optional[str]:
    """Return the keyword rule category for *title*, or None.

    Longer keywords are tried first so "uber eats" beats "uber".
    """
    key = normalize_merchant(title)
    if not key:
        return None
    for keyword in sorted(KEYWORD_RULES, key=len, reverse=True):
        if keyword in key:
            return KEYWORD_RULES[keyword]
    return None


class CategorizationService:
    """Picks a category per user, with a memory of learned mappings."""

    def __init__(self, db: Session, llm_fn: Optional[LLMFn] = None) -> None:
        self.db = db
        self.llm_fn = llm_fn

    # ── Learned mapping ──────────────────────────────────────────────────

    def learned_category(self, user_id: int, merchant_key: str) -> Optional[str]:
        if not merchant_key:
            return None
        return self.db.execute(
            select(MerchantCategoryORM.category).where(
                MerchantCategoryORM.user_id == user_id,
                MerchantCategoryORM.merchant == merchant_key,
            )
        ).scalar_one_or_none()

    def learn(
        self, user_id: int, title: str, category: str, source: str = "user"
    ) -> None:
        """Upsert a merchant → category mapping for *user_id*.

        A ``"user"`` rename always wins; less trusted sources (``"llm"``)
        never overwrite an existing ``"user"`` mapping.
        """
        key = normalize_merchant(title)
        if not key or not category:
            return
        existing = self.db.execute(
            select(MerchantCategoryORM).where(
                MerchantCategoryORM.user_id == user_id,
                MerchantCategoryORM.merchant == key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if source != "user" and existing.source == "user":
                return  # don't let an LLM guess clobber a manual rename
            existing.category = category
            existing.source = source
        else:
            self.db.add(
                MerchantCategoryORM(
                    user_id=user_id, merchant=key, category=category, source=source
                )
            )
        self.db.flush()

    # ── Resolution ───────────────────────────────────────────────────────

    def categorize(
        self,
        user_id: int,
        title: str,
        *,
        default: Optional[str] = None,
        use_llm: bool = False,
    ) -> tuple[str, str]:
        """Resolve a single transaction's category.

        Returns ``(category, source)`` where source is one of
        ``learned`` / ``rule`` / ``llm`` / ``default``.
        """
        key = normalize_merchant(title)

        learned = self.learned_category(user_id, key)
        if learned:
            return learned, "learned"

        rule = rule_category(title)
        if rule:
            return rule, "rule"

        if use_llm and self.llm_fn is not None:
            llm_cat = self._llm_lookup([title]).get(title)
            if llm_cat:
                self.learn(user_id, title, llm_cat, source="llm")
                return llm_cat, "llm"

        return (default or DEFAULT_CATEGORY), "default"

    def categorize_batch(
        self,
        user_id: int,
        titles: list[str],
        *,
        defaults: Optional[dict[str, str]] = None,
        use_llm: bool = True,
    ) -> dict[str, str]:
        """Resolve many titles at once, batching the Groq call for unknowns.

        Learned mappings and keyword rules are resolved locally; only the
        remaining unknowns are sent to ``llm_fn`` in a single batched call.
        """
        defaults = defaults or {}
        result: dict[str, str] = {}
        unknown: list[str] = []

        for title in titles:
            key = normalize_merchant(title)
            learned = self.learned_category(user_id, key)
            if learned:
                result[title] = learned
                continue
            rule = rule_category(title)
            if rule:
                result[title] = rule
                continue
            unknown.append(title)

        if unknown and use_llm and self.llm_fn is not None:
            llm_map = self._llm_lookup(unknown)
            for title in list(unknown):
                cat = llm_map.get(title)
                if cat:
                    self.learn(user_id, title, cat, source="llm")
                    result[title] = cat
                    unknown.remove(title)

        for title in unknown:
            result[title] = defaults.get(title, DEFAULT_CATEGORY)

        return result

    def _llm_lookup(self, titles: list[str]) -> dict[str, str]:
        """Call the injected Groq function, swallowing any failure."""
        if self.llm_fn is None:
            return {}
        try:
            return self.llm_fn(titles) or {}
        except Exception:  # noqa: BLE001  LLM or network errors must never break ingestion
            return {}
