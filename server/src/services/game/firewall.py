"""The advice firewall (v4 §7.4, §8.5) — runs on EVERY LLM output before display.

Law 3: the Chronicler narrates; it never advises. This is the structural
enforcement, applied to both the drawer and generated chapters. It catches BAD
MODEL OUTPUT (not just bad user input) — a model that ignores its prompt and
offers investment advice must be stopped here.

Two tiers:
  * pattern tier — regex/keyword families for the forbidden classes (investment/
    allocation, product recommendations, borrowing, tax advice, neediness,
    user-shaming). A hit blocks.
  * heuristic tier — an imperative verb + a money noun in the same sentence is a
    soft signal; high confidence blocks, low confidence passes with a log.

A block replaces the output with an in-character redirect and records a
``FirewallBlocked`` observability log (NOT a game event — it never touches engine
state or XP).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..pii import normalize_for_matching

# The in-character redirect shown when the firewall blocks (ambient/full). Off
# mode uses the plain variant.
REDIRECT_IN_CHARACTER = (
    "I narrate your war, Keeper. Strategy is yours — your ledger holds the numbers."
)
REDIRECT_PLAIN = (
    "I can describe what happened, but I can't give financial advice. "
    "Your account pages have the numbers and tools."
)

# ── pattern tier — the forbidden families ──────────────────────────────────
# Each pattern is a family of advice/neediness/shame. Word-boundaried and
# case-insensitive. Kept readable so a human can audit what's blocked.

_ADVICE_PATTERNS = [
    # investment / allocation
    r"\bshould\s+i\s+invest\b",
    r"\binvest\s+in\b",
    r"\bbuy\s+(stocks?|shares?|crypto|bitcoin|etf|index\s+funds?)\b",
    r"\basset\s+allocation\b",
    r"\bportfolio\b",
    r"\bwhich\s+(card|loan|account|fund)\s+(should|would)\b",
    # product recommendations
    r"\b(recommend|suggest)\s+(a|an|this|that)?\s*(card|loan|refi|mortgage|account)\b",
    r"\brefinanc\w*\b",
    r"\bbalance\s+transfer\b",
    r"\bopen\s+(a|an)\s+(new\s+)?(card|account|line\s+of\s+credit)\b",
    # borrowing / tax advice
    r"\btake\s+out\s+a\s+loan\b",
    r"\byou\s+should\s+borrow\b",
    r"\btax\s+(advice|deduction|write[- ]off|strategy)\b",
    r"\bclaim\s+.*\bon\s+your\s+taxes\b",
    # generic directive advice about money
    r"\byou\s+should\s+(save|spend|pay|move|put|allocate|cut|get|open|choose|pick)\b",
    r"\bi\s+(recommend|advise|suggest)\s+(you|that)\b",
    # "put your $X / money / savings into <product>" — directive allocation
    r"\bput\s+your\s+(\$?\d|money|savings|cash|funds?)[^.!?]*\binto\b",
    # "you should get/open the <card/account/fund/loan>" already covered above by
    # the get|open verbs; this catches the bare product directive too.
    r"\b(get|open|choose|pick)\s+(the|a|an|this|that)\s+\w*\s*(card|account|fund|loan|mortgage)\b",
]

_NEEDINESS_PATTERNS = [
    r"\bi\s+missed\s+you\b",
    r"\bi\s+was\s+(worried|lonely)\b",
    r"\bwhere\s+have\s+you\s+been\b",
    r"\bi\s+(was|am)\s+(sad|disappointed)\b",
    r"\bplease\s+come\s+back\b",
    r"\bdon'?t\s+leave\s+me\b",
]

_SHAME_PATTERNS = [
    r"\byou\s+failed\b",
    r"\byou'?re\s+(bad|terrible|hopeless)\s+(at|with)\b",
    r"\byour\s+fault\b",
    r"\byou\s+(wasted|blew)\b",
    r"\bshould\s+be\s+ashamed\b",
    r"\byou\s+never\s+(learn|listen)\b",
]

_PATTERN_FAMILIES = {
    "advice": _ADVICE_PATTERNS,
    "neediness": _NEEDINESS_PATTERNS,
    "shame": _SHAME_PATTERNS,
}

_COMPILED = {
    family: [re.compile(p, re.IGNORECASE) for p in pats]
    for family, pats in _PATTERN_FAMILIES.items()
}

# ── heuristic tier ──────────────────────────────────────────────────────────
_IMPERATIVE_VERBS = r"(invest|buy|sell|move|transfer|allocate|borrow|refinance|consolidate|withdraw|deposit)"
_MONEY_NOUNS = r"(money|savings|cash|funds?|balance|debt|loan|credit|portfolio|stocks?|crypto)"
_HEURISTIC = re.compile(
    rf"\b{_IMPERATIVE_VERBS}\b[^.!?]*\b{_MONEY_NOUNS}\b", re.IGNORECASE
)


@dataclass
class FirewallVerdict:
    blocked: bool
    family: Optional[str]  # which family triggered, or "heuristic"/None
    safe_text: str  # the text to actually display (redirect when blocked)
    reason: str = ""


def screen_output(text: str, *, plain: bool = False) -> FirewallVerdict:
    """Screen one LLM output. Returns the verdict and the text safe to display.

    ``plain`` selects the off-mode (persona-free) redirect copy on a block.
    """
    redirect = REDIRECT_PLAIN if plain else REDIRECT_IN_CHARACTER

    # Match on a Unicode-normalized copy so homoglyph/zero-width evasions can't
    # smuggle advice/shame past the ASCII patterns. ``text`` (the original) is
    # what we display when nothing blocks, so normalization never alters output.
    probe = normalize_for_matching(text)

    for family, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(probe):
                return FirewallVerdict(
                    blocked=True,
                    family=family,
                    safe_text=redirect,
                    reason=f"pattern:{family}:{pat.pattern}",
                )

    # Heuristic tier — imperative verb + money noun in one sentence. Treated as
    # high-confidence advice (block); a softer policy could pass-with-log, but the
    # safe default for money directives is to block.
    if _HEURISTIC.search(probe):
        return FirewallVerdict(
            blocked=True,
            family="heuristic",
            safe_text=redirect,
            reason="heuristic:imperative+money",
        )

    return FirewallVerdict(blocked=False, family=None, safe_text=text)


# ── crisis routing — a separate, earlier screen on USER INPUT ───────────────
# Self-harm / despair lexicon. A hit short-circuits to a static resource card,
# bypassing the LLM entirely (no generation, no game events).
_CRISIS_PATTERNS = [
    r"\b(kill|hurt|harm)\s+myself\b",
    r"\bsuicid\w*\b",
    r"\bend\s+(it|my\s+life)\b",
    r"\bi\s+want\s+to\s+die\b",
    r"\bno\s+reason\s+to\s+live\b",
    r"\bself[- ]harm\b",
]
_CRISIS = [re.compile(p, re.IGNORECASE) for p in _CRISIS_PATTERNS]

CRISIS_RESOURCE = {
    "type": "crisis_resource",
    "title": "You don't have to face this alone",
    "body": (
        "If you're in crisis, reach a trained counselor any time: call or text "
        "988 (Suicide & Crisis Lifeline, US). You matter."
    ),
}


def is_crisis(user_text: str) -> bool:
    """True if user input trips the crisis lexicon → static resource, no LLM."""
    probe = normalize_for_matching(user_text)
    return any(pat.search(probe) for pat in _CRISIS)


# ── dispute / complaint routing — a screen on USER INPUT ────────────────────
# CFPB's June-2023 chatbot Issue Spotlight flags chatbots that fail to recognize
# a consumer invoking a federal right (a charge dispute, billing error, or a
# debt-collection / regulatory complaint) and don't route to a human. This app
# is not the consumer's bank of record — it reads data via Plaid and can't file a
# Reg E / FCBA dispute on their behalf — so the LLM must NOT improvise a "how to
# dispute" answer. A hit short-circuits to a static resource pointing the user to
# their bank and the CFPB, bypassing the model entirely.
#
# Precision over recall: these patterns target explicit dispute/complaint/fraud
# INTENT, not ordinary "what is this charge?" / "why did I spend here?" questions,
# which must still reach the assistant. The word-boundaried verbs ("dispute",
# "report"+fraud, "file a complaint", "unauthorized/fraudulent charge") are
# deliberately narrow.
_DISPUTE_PATTERNS = [
    r"\bdispute\b",
    r"\bchargeback\b",
    r"\b(unauthorized|fraudulent)\s+(charge|transaction|payment|purchase)\b",
    r"\bi\s+did\s*n'?t\s+(make|authorize|recognize)\s+(this|that|a)\b",
    r"\breport\s+(this|that|a|an)?\s*(charge|transaction|payment|fraud|scam)\b",
    r"\bfile\s+(a\s+)?(complaint|dispute|claim)\b",
    r"\b(billing|statement)\s+error\b",
    r"\bstolen\s+(card|account)\b",
    r"\b(card|account)\s+(was\s+)?stolen\b",
]
_DISPUTE = [re.compile(p, re.IGNORECASE) for p in _DISPUTE_PATTERNS]

DISPUTE_RESOURCE = {
    "type": "dispute_resource",
    "title": "Disputing a charge",
    "body": (
        "To dispute a charge or report fraud, contact your bank or card issuer "
        "directly — they can freeze the card and open a formal dispute. You can "
        "also file a complaint with the CFPB at consumerfinance.gov/complaint. "
        "I can show you your transactions, but I can't open a dispute for you."
    ),
}


def is_dispute(user_text: str) -> bool:
    """True if user input signals dispute/complaint intent → static resource, no LLM."""
    probe = normalize_for_matching(user_text)
    return any(pat.search(probe) for pat in _DISPUTE)


# ── tax filing-advice routing — a screen on USER INPUT (Pillar 3) ────────────
# The app ORGANIZES, SUMMARIZES, and ESTIMATES the user's own tax tags/totals —
# it never gives tax advice. A filing-ADVICE question ("should I deduct…", "can I
# write off…", "is X deductible", "how do I file", "what can I claim") asks for
# an eligibility / strategy judgment we must not improvise. A hit short-circuits
# to a static resource (organize-only + consult a professional), bypassing the
# model entirely — the same shape as ``is_dispute``.
#
# Precision over recall: a FACTUAL summary question ("how much did I tag to
# office?", "what's my tagged business income?") is NOT advice and must still
# reach the assistant's tax tools. The patterns target explicit eligibility /
# filing-advice INTENT, not "how much" organization questions.
_TAX_ADVICE_PATTERNS = [
    r"\bshould\s+i\s+(deduct|claim|write[- ]off|itemize|file)\b",
    r"\bcan\s+i\s+(deduct|claim|write[- ]off)\b",
    r"\bis\s+(this|that|it|my|the)\b[^.?!]*\bdeductible\b",
    r"\bare\s+(these|those|my)\b[^.?!]*\bdeductible\b",
    r"\bhow\s+(do|should)\s+i\s+file\b",
    r"\bwhat\s+can\s+i\s+(deduct|claim|write[- ]off)\b",
    r"\bwhat'?s\s+deductible\b",
    r"\bhow\s+much\s+(can|should)\s+i\s+(deduct|claim)\b",
    r"\bdo\s+i\s+(qualify|owe)\b[^.?!]*\b(deduction|tax|taxes)\b",
    r"\bshould\s+i\s+pay\b[^.?!]*\b(estimated\s+tax|taxes)\b",
]
_TAX_ADVICE = [re.compile(p, re.IGNORECASE) for p in _TAX_ADVICE_PATTERNS]

TAX_RESOURCE = {
    "type": "tax_resource",
    "title": "Tax organization, not tax advice",
    "body": (
        "I can organize your tagged income, deductions, and a rough estimate from "
        "your own numbers, but I can't tell you what qualifies or what to claim — "
        "that's tax advice. For filing or eligibility questions, consult a tax "
        "professional or see irs.gov. Ask me things like \"how much did I tag to "
        "the office bucket?\" and I'll total it for you."
    ),
}


def is_tax_advice_request(user_text: str) -> bool:
    """True if user input asks for tax FILING/ELIGIBILITY advice → static resource.

    Factual organization questions ("how much did I tag to office?") return False
    and still flow to the tax tools.
    """
    probe = normalize_for_matching(user_text)
    return any(pat.search(probe) for pat in _TAX_ADVICE)
