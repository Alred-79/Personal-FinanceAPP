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

    for family, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(text):
                return FirewallVerdict(
                    blocked=True,
                    family=family,
                    safe_text=redirect,
                    reason=f"pattern:{family}:{pat.pattern}",
                )

    # Heuristic tier — imperative verb + money noun in one sentence. Treated as
    # high-confidence advice (block); a softer policy could pass-with-log, but the
    # safe default for money directives is to block.
    if _HEURISTIC.search(text):
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
    return any(pat.search(user_text) for pat in _CRISIS)
