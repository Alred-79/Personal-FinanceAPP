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
import unicodedata
from typing import Any

# ── Unicode normalization (applied BEFORE any regex) ────────────────────────
# Regex guardrails are trivially bypassable with Unicode tricks: a full-width
# SSN (``１２３-４５-６７８９``) or digits separated by zero-width joiners slip past
# an ASCII ``\d{3}-\d{2}-\d{4}`` and reach the LLM unredacted; the same evasion
# beats the advice/shame firewall via homoglyphs. NFKC folds full-width and
# other compatibility forms back to ASCII, and stripping format/control
# characters (Cf/Cc — zero-width joiner/space, BOM, bidi marks, soft hyphen)
# collapses interleaved-invisible evasions. Normalize once, then match.
# (OWASP LLM01:2025; "Bypassing Prompt Injection and Jailbreak Detection",
# arXiv:2504.11168.)
_FORMAT_CONTROL = {"Cf", "Cc"}


def normalize_for_matching(text: str) -> str:
    """NFKC-normalize and strip invisible format/control chars before regex.

    Returns text safe to run deterministic guardrail patterns against. Newlines
    and tabs are preserved (they carry layout, not evasion); other Cc/Cf code
    points (zero-width joiner/space, BOM, bidi overrides, soft hyphen) are
    dropped so an SSN/advice phrase can't be smuggled past a regex by
    interleaving invisible characters.
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(
        ch
        for ch in normalized
        if ch in ("\n", "\t") or unicodedata.category(ch) not in _FORMAT_CONTROL
    )


# ── high-risk patterns (always redacted) ────────────────────────────────────
# Ordered most-specific first so a card number isn't half-matched as a phone.
_REDACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    # US SSN (with or without dashes), avoiding matches inside longer digit runs
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # US EIN (employer/payer TIN), dashed form XX-XXXXXXX. Placed BEFORE the
    # card/account rules: the account rule (\b\d{8,17}\b) needs 8+ CONTIGUOUS
    # digits so it can't match the dashed EIN, but the card rule ((?:\d[ -]?)…)
    # tolerates separators — so the EIN must be tagged here first to guarantee a
    # tax-doc EIN reads as [REDACTED_EIN], never swallowed as a partial card/acct
    # run. (Pillar 3: tax-document PII gets a stricter stance than receipts.) A
    # bare 9-digit run with no dash is still handled by the account rule below,
    # unchanged.
    (re.compile(r"\b\d{2}-\d{7}\b"), "[REDACTED_EIN]"),
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
    # Normalize first so Unicode-obfuscated secrets (full-width / zero-width
    # interleaved) can't slip past the ASCII patterns below.
    out = normalize_for_matching(text)
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
