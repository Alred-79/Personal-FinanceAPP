"""Rule-based PII scrubbing for text leaving the app for a third-party LLM.

Best practice (OWASP LLM Top 10 2025; financial-LLM guidance) is to minimize
sensitive data *before* it reaches a third-party inference provider, and to do
the redaction with **deterministic rules** — not an LLM, which can silently
reconstruct what it was asked to hide and offers no audit trail.

Two concerns are separated here:

1. ``scrub_secrets`` — ALWAYS-ON redaction of high-risk tokens that are never
   needed for budgeting and are pure leak risk if they appear in a transaction
   memo / account label: bank/card/routing numbers, SSNs, emails, phone numbers.
   This never removes a merchant name, so the assistant stays useful.

2. ``minimize_merchant`` — OPT-IN minimization (gated by a user preference) that
   replaces a merchant/account label with a category-based placeholder, for
   privacy-conscious users who don't want merchant names shipped to Groq at all.

Both operate on the tool-output payloads (dicts / lists / strings) the assistant
hands to the model, and on the model's own streamed output is screened separately
by the advice firewall.
"""

from __future__ import annotations

import re
from typing import Any

# ── high-risk patterns (always redacted) ────────────────────────────────────
# Ordered most-specific first so a card number isn't half-matched as a phone.
_REDACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    # US SSN (with or without dashes), avoiding matches inside longer digit runs
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # email addresses
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED_EMAIL]"),
    # 13–19 digit card / 8–17 digit account/routing runs (allow spaces/dashes as
    # separators), bounded so ordinary amounts/ids don't trip it.
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b\d{8,17}\b"), "[REDACTED_ACCT]"),
    # US-style phone numbers
    (re.compile(r"\b(?:\+?1[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b"), "[REDACTED_PHONE]"),
]

# Fields in a transaction/account dict that carry a free-text label a user (or a
# bank memo) could stuff sensitive content into.
_TEXT_FIELDS = ("title", "name", "description", "merchant", "memo", "note")
# The merchant/label fields that opt-in minimization replaces with a placeholder.
_LABEL_FIELDS = ("title", "name", "merchant")


def scrub_secrets(text: str) -> str:
    """Redact high-risk tokens (SSN/email/card/account/phone) from *text*.

    Always safe to call; leaves ordinary merchant names and amounts intact.
    """
    if not text:
        return text
    out = text
    for pattern, repl in _REDACTION_RULES:
        out = pattern.sub(repl, out)
    return out


def _placeholder_for(value: str, category: str | None) -> str:
    """A category-based stand-in for a merchant label under minimization."""
    cat = (category or "").strip()
    return f"[{cat} merchant]" if cat else "[merchant]"


def redact_payload(payload: Any, *, minimize_merchants: bool = False) -> Any:
    """Recursively scrub a tool-output payload before it is shown to the LLM.

    * Always runs ``scrub_secrets`` on every string value.
    * When *minimize_merchants* is True, also replaces merchant/label fields in
      transaction-shaped dicts with a category-based placeholder.

    Returns a new structure; never mutates the input.
    """
    if isinstance(payload, str):
        return scrub_secrets(payload)

    if isinstance(payload, list):
        return [redact_payload(item, minimize_merchants=minimize_merchants) for item in payload]

    if isinstance(payload, dict):
        category = payload.get("category")
        out: dict[Any, Any] = {}
        for key, value in payload.items():
            if (
                minimize_merchants
                and key in _LABEL_FIELDS
                and isinstance(value, str)
                and value
            ):
                out[key] = _placeholder_for(value, category)
            elif key in _TEXT_FIELDS and isinstance(value, str):
                out[key] = scrub_secrets(value)
            else:
                out[key] = redact_payload(
                    value, minimize_merchants=minimize_merchants
                )
        return out

    # ints / floats / None / bools pass through unchanged.
    return payload
