"""T2 challenge verdicts — the LLM/Tavily side ONLY (v4 §8.6, Law 2).

This module fetches web reference facts (Tavily) and produces a STRUCTURED
verdict ``{met: bool, evidence_ref: str, text: str}``. It awards NOTHING and
records NOTHING: the engine (:mod:`challenges`) reads only the structured
fields, re-resolves ``evidence_ref`` against the fetched sources, and awards XP
itself. A test asserts this module's source contains no event-recording call —
the LLM handler is structurally incapable of feeding engine state.

Verdict text is flavor. It passes the package-07 firewall before any surface
renders it, and the engine never parses it.
"""

from __future__ import annotations

import json
from typing import Callable, Optional


def fetch_reference(
    query: str, *, search_fn: Optional[Callable[[str], dict]] = None
) -> list[dict]:
    """Fetch web reference facts for a T2 challenge via Tavily.

    Returns ``[{"url": ..., "content": ...}, ...]``. ``search_fn`` is injected
    in tests; the default builds a real TavilyClient. Any failure returns an
    empty list — no references means the verdict can never resolve, which
    voids the challenge quietly downstream (pro-player: a flaky fetch never
    costs the user anything).
    """
    try:
        if search_fn is None:
            from tavily import TavilyClient

            from ...settings import settings

            client = TavilyClient(api_key=settings.tavily_api_key)
            search_fn = client.search
        response = search_fn(query) or {}
        return [
            {"url": r.get("url", ""), "content": r.get("content", "")}
            for r in response.get("results", [])
            if r.get("url")
        ]
    except Exception:
        return []


def structured_verdict(
    challenge_params: dict,
    references: list[dict],
    *,
    llm_call: Optional[Callable[[str], str]] = None,
) -> dict:
    """Produce the structured T2 verdict from the reference facts.

    ``llm_call`` takes the prompt and returns the raw model string (JSON).
    Without one (no key wired / model down), the verdict is the conservative
    constant ``{met: False, evidence_ref: "", text: ""}`` — never met, never
    awarded, challenge voids quietly.

    The returned dict is schema-clamped: ``met`` is coerced to bool,
    ``evidence_ref`` to str. Malformed model output collapses to not-met.
    """
    if llm_call is None or not references:
        return {"met": False, "evidence_ref": "", "text": ""}
    prompt = json.dumps(
        {
            "task": "challenge_verdict",
            "params": challenge_params,
            "references": references,
            "format": {"met": "bool", "evidence_ref": "url", "text": "string"},
        },
        sort_keys=True,
    )
    try:
        raw = llm_call(prompt)
        parsed = json.loads(raw)
        return {
            "met": bool(parsed.get("met", False)),
            "evidence_ref": str(parsed.get("evidence_ref", "") or ""),
            "text": str(parsed.get("text", "") or ""),
        }
    except Exception:
        return {"met": False, "evidence_ref": "", "text": ""}
