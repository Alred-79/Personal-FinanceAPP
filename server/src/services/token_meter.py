"""Token counting + Groq-usage extraction for the LLM dollar cap (A3).

The chat path needs a *real* cost figure to enforce a per-user daily dollar
ceiling. Two sources, in order of trust:

1. **Exact Groq usage.** When a streamed response carries ``usage_metadata``
   (langchain_groq maps Groq's returned token_usage onto the final
   ``AIMessageChunk``), use its ``input_tokens`` / ``output_tokens`` verbatim —
   this is the bill's own numbers.
2. **Local tiktoken fallback.** When usage is absent, count tokens locally with
   tiktoken over the text. Approximate (a different tokenizer than Groq's) but
   enforceable, and never an under-count by much for English text.

Pricing converts tokens → cents at ``settings.groq_*_price_cents_per_mtok`` so
the cap is denominated in money, not tokens.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from server.src.settings import settings

# A single cl100k_base encoder is a good-enough proxy for a Llama tokenizer for
# *budgeting* (we only need order-of-magnitude-correct counts to bound spend).
# Loaded lazily so importing this module never does network/disk work at import.
_ENCODER = None


def _encoder():
    global _ENCODER
    if _ENCODER is None:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


def count_tokens(text: str) -> int:
    """Approximate token count for *text* via tiktoken (fallback source)."""
    if not text:
        return 0
    try:
        return len(_encoder().encode(text))
    except Exception:
        # Never let metering crash a chat: fall back to the ~4-chars/token heuristic.
        return max(1, len(text) // 4)


def usage_from_message(message: Any) -> Optional[tuple[int, int]]:
    """Extract ``(input_tokens, output_tokens)`` from a model output message.

    Returns None when no usage is present (caller then uses the tiktoken count).
    Handles the modern ``usage_metadata`` dict and the older
    ``response_metadata['token_usage']`` shape Groq sometimes uses.
    """
    if message is None:
        return None
    um = getattr(message, "usage_metadata", None)
    if isinstance(um, dict) and um.get("input_tokens") is not None:
        return int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))
    rm = getattr(message, "response_metadata", None)
    if isinstance(rm, dict):
        tu = rm.get("token_usage") or rm.get("usage")
        if isinstance(tu, dict) and tu.get("prompt_tokens") is not None:
            return int(tu.get("prompt_tokens", 0)), int(tu.get("completion_tokens", 0))
    return None


def message_text(message: Any) -> str:
    """Best-effort plain text of a model output message, for tiktoken fallback
    counting of a sub-run that returned no ``usage_metadata``.

    Handles a str ``content``, a list-of-parts content (concatenating the text
    parts), and a bare string. Returns "" when nothing textual is present.
    """
    if message is None:
        return ""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return "".join(parts)
    return ""


def cost_cents(input_tokens: int, output_tokens: int) -> int:
    """Price tokens into cents, rounding UP so the cap is never under-charged."""
    in_cents = (input_tokens * settings.groq_input_price_cents_per_mtok) / 1_000_000
    out_cents = (output_tokens * settings.groq_output_price_cents_per_mtok) / 1_000_000
    return math.ceil(in_cents + out_cents)


def estimate_cost_cents(prompt_text: str, *, expected_output_tokens: int = 600) -> int:
    """A conservative PRE-FLIGHT cost estimate (before the model runs).

    Counts the prompt with tiktoken and assumes a generous output length so the
    reservation errs toward over-reserving (then reconciles down to actual).
    """
    return cost_cents(count_tokens(prompt_text), expected_output_tokens)
