"""Deterministic per-turn mode-gating tool-router (W1, Feature 1).

A per-turn classifier selects which **tool groups** the assistant sees, mirroring
the advice firewall's mechanism (Unicode-normalized text + compiled regex
families, no LLM call). Groups are **additive**: a ``READ`` base is always
present, ``MONEY`` is part of the standing core, and ``WEB`` / ``TAX`` are gated
in only when their intent fires. Worst case (ambiguous / multi-intent) = the
union of fired groups — which equals today's full toolset — so the router never
removes capability the user demonstrably needs.

Wins: lower per-turn token cost (fewer tool schemas in the prompt), a smaller
safety surface (the web tools only join on explicit look-up intent, shrinking the
SSRF/cost surface), and headroom as the toolset grows.

This module is PURE and DETERMINISTIC: ``classify_mode`` makes no DB or network
call and is a function of ``(text, tax_enabled)`` only. It mirrors
``services/game/firewall.py`` so a human can audit exactly what each group keys
off. Tax FILING advice is short-circuited by the firewall (``is_tax_advice_request``)
*before* the router ever runs, so the ``_TAX_ORGANIZE`` family here only needs to
catch organize/summarize intent.
"""

from __future__ import annotations

import re

from .pii import normalize_for_matching

# ── tool-group names ────────────────────────────────────────────────────────
# Group → the assistant tools that belong to it. The actual BaseTool instances
# live in ``assistant_service``; the router only deals in group names and the
# stable ``mode_signature`` string, so it stays import-light and testable.
READ = "read"
MONEY = "money"
WEB = "web"
TAX = "tax"

# Tool name → group. The single source of truth for "which tools does this group
# carry". ``assistant_service`` filters its built tool list against the selected
# groups using this map, so adding a tool to a group is a one-line change here.
TOOL_GROUPS: dict[str, str] = {
    # READ (always present): the read-only data tools.
    "get_transactions_by_date_range": READ,
    "get_transactions_by_category": READ,
    "get_accounts": READ,
    "get_transactions_per_account": READ,
    "get_spend_details": READ,
    "get_goals": READ,
    # MONEY (standing core): the propose-only write / planning tools.
    "add_transaction": MONEY,
    "add_goal": MONEY,
    "recategorize_transaction": MONEY,
    "what_if": MONEY,
    "create_rule": MONEY,
    "propose_assisted_action": MONEY,
    # WEB (gated on look-up intent): the egress tools.
    "search_web": WEB,
    "open_website": WEB,
    "get_information": WEB,
    # TAX (gated on organize intent AND tax_features_enabled): the tax tools.
    "tag_transaction_tax": TAX,
    "get_tax_summary": TAX,
    "get_deductions_by_bucket": TAX,
}


def group_for_tool(tool_name: str) -> str | None:
    """The group a tool belongs to, or ``None`` if the tool is unknown."""
    return TOOL_GROUPS.get(tool_name)


# ── lexicons (compiled regex families, mirroring firewall.py) ───────────────
# Word-boundaried, case-insensitive, matched on Unicode-normalized text so a
# homoglyph/zero-width evasion can't smuggle intent past the ASCII patterns.
# Lexicons are taken from PLAN-router-and-feedback-loop.md Feature 1.

# MONEY — move/transfer/pay/save/set aside/fund/automate/rule/alert/
# add (a/an) transaction/recategorize/what if/raise. (MONEY is standing-core so
# this family is unused for the default decision; it is kept so the machinery
# supports a future pure-READ mode that only adds MONEY on these signals.)
_MONEY_PATTERNS = [
    r"\b(move|transfer|send)\b",
    r"\bpay\b",
    r"\b(save|saving|set\s+aside|put\s+aside|stash)\b",
    r"\bfund\b",
    r"\b(automate|automat\w+|rule|recurring|every\s+time|whenever)\b",
    r"\balert\b",
    r"\badd\s+(a|an|the)?\s*(transaction|expense|income|goal)\b",
    r"\brecategoriz\w*\b",
    r"\bwhat[\s-]?if\b",
    r"\b(raise|afford)\b",
    r"\bcreate\s+(a|an)?\s*(goal|rule|budget)\b",
]

# WEB — look up/search/google/what is the price/current/latest/news.
_WEB_PATTERNS = [
    r"\blook\s+up\b",
    r"\b(search|google|bing)\b",
    r"\bopen\s+(the\s+)?(website|page|url|link)\b",
    r"\b(go\s+to|visit|browse)\s+\w",
    r"\bwhat\s+is\s+the\s+(price|cost|value)\s+of\b",
    r"\b(current|latest|today'?s)\s+(price|rate|value|news)\b",
    r"\bnews\b",
    r"\bon\s+the\s+(web|internet)\b",
    r"\bhttps?://",
]

# TAX — deduct(only org-context)/schedule c/bucket/1099/1098/write-off/
# tax summary. Tax *advice* ("should I deduct…", "is X deductible") is
# short-circuited by the firewall BEFORE the router, so this only catches
# organize/summarize intent.
_TAX_ORGANIZE_PATTERNS = [
    r"\btax\s+(summary|bucket|total|report|organiz\w+)\b",
    r"\bschedule\s+c\b",
    r"\b(bucket|buckets)\b",
    r"\b(1099|1098|w-?2)\b",
    r"\bwrite[\s-]?off\b",
    r"\bdeduct\w*\b",
    r"\bdeductible\b",
    r"\btag\b[^.?!]*\btax\b",
    r"\btax\s*(es)?\b[^.?!]*\b(tag|tagged|bucket|total|summary)\b",
]

_MONEY = [re.compile(p, re.IGNORECASE) for p in _MONEY_PATTERNS]
_WEB = [re.compile(p, re.IGNORECASE) for p in _WEB_PATTERNS]
_TAX_ORGANIZE = [re.compile(p, re.IGNORECASE) for p in _TAX_ORGANIZE_PATTERNS]


def _any(patterns: list[re.Pattern[str]], probe: str) -> bool:
    return any(pat.search(probe) for pat in patterns)


# Canonical group ordering for a stable ``mode_signature`` string. Order is
# fixed (read → money → web → tax) so the same fired set always produces the
# same signature regardless of match order — the signature is a cache key.
_SIGNATURE_ORDER = (READ, MONEY, WEB, TAX)


def mode_signature(groups: frozenset[str]) -> str:
    """A stable, deterministic signature for a group set, e.g. ``"read+money"``.

    Used as part of the executor cache key ``(user_id, mode_signature)``.
    """
    return "+".join(g for g in _SIGNATURE_ORDER if g in groups)


def classify_mode(text: str, *, tax_enabled: bool) -> tuple[frozenset[str], str]:
    """Deterministically pick the tool groups for one turn.

    Returns ``(groups, mode_signature)``:

    * ``READ`` is ALWAYS present.
    * ``MONEY`` is standing-core — present on every turn (the plan doc's initial
      policy keeps financial conversation fully capable; money false-negatives
      are costly, so writes are not gated yet). A future phase-2 pure-READ mode
      can drop MONEY on unambiguous data questions; the ``_MONEY`` lexicon is
      defined for that day.
    * ``WEB`` is added only on explicit look-up / search intent.
    * ``TAX`` is added only on tax-organize intent AND ``tax_enabled``; even on a
      clear tax intent it stays hidden when the feature flag is off.

    Ambiguous / multi-intent text unions every fired group (worst case = today's
    full set). Pure logic — no DB, no network, no LLM.
    """
    probe = normalize_for_matching(text or "")

    groups = {READ, MONEY}

    if _any(_WEB, probe):
        groups.add(WEB)
    if tax_enabled and _any(_TAX_ORGANIZE, probe):
        groups.add(TAX)

    frozen = frozenset(groups)
    return frozen, mode_signature(frozen)
