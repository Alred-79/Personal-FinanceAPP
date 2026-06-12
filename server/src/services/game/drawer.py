"""The Chronicler drawer (v4 §7.4, task 6).

The drawer is the EXISTING assistant with a skin — same data access, same
propose→confirm safety. This module adds only: the persona prompt (ambient/full;
plain in off), the advice firewall on output (buffer → filter → render, never
stream raw model text), crisis routing (a keyword screen that bypasses the LLM),
and a per-day rate limit with an in-character refusal.

It does NOT build a second agent and does NOT add a propose-tool — writes still
flow through the assistant's propose→confirm path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .firewall import CRISIS_RESOURCE, is_crisis, screen_output

DAILY_MESSAGE_LIMIT = 20  # config; the cap before an in-character refusal

# Persona epithets present in ambient/full, absent in off — the "skin".
PERSONA_EPITHET = "Keeper"
RATE_LIMIT_REFUSAL_FULL = (
    "Enough war-talk for one day, Keeper. The chronicle resumes tomorrow."
)
RATE_LIMIT_REFUSAL_PLAIN = (
    "You've reached today's message limit. It resets tomorrow."
)


@dataclass
class DrawerResponse:
    text: str
    kind: str = "message"  # message | crisis | refusal | redirect
    persona: bool = False
    ai_label: bool = True  # the persistent AI label is ALWAYS present
    blocked: bool = False
    meta: dict = field(default_factory=dict)


def persona_system_prompt(mode: str) -> str:
    """The system prompt prefix that skins the assistant. Off mode = plain
    assistant, zero persona; ambient/full = the Chronicler voice."""
    if mode == "off":
        return ""  # plain assistant — no persona tokens at all
    register = "roast" if mode == "full" else "gentle"
    return (
        f"You are the Chronicler, narrating for the Keeper (register: {register}). "
        "You answer questions about the ledger plainly, but in voice. You NEVER "
        "give financial advice, recommend products, or invent numbers."
    )


class ChroniclerDrawer:
    """Wraps an assistant 'respond' callable with crisis screen + firewall +
    rate limit. The callable takes (user, message, system_prefix) and returns the
    buffered model text (already run through the assistant's tools)."""

    def __init__(self, respond_fn) -> None:
        self._respond = respond_fn
        # Per-user in-memory daily counters: {user_id: (date_iso, count)}.
        self._counts: dict[int, tuple[str, int]] = {}

    def _bump(self, user_id: int, today_iso: str) -> int:
        day, count = self._counts.get(user_id, (today_iso, 0))
        if day != today_iso:
            count = 0
        count += 1
        self._counts[user_id] = (today_iso, count)
        return count

    def ask(self, user, message: str, *, today_iso: str) -> DrawerResponse:
        mode = getattr(user, "game_mode", "off")
        plain = mode == "off"

        # 1. Crisis screen FIRST — bypasses the LLM entirely (no generation, no
        #    game events). A life-safety path must never depend on the model.
        if is_crisis(message):
            return DrawerResponse(
                text=CRISIS_RESOURCE["body"],
                kind="crisis",
                persona=False,
                meta=CRISIS_RESOURCE,
            )

        # 2. Rate limit.
        count = self._bump(user.id, today_iso)
        if count > DAILY_MESSAGE_LIMIT:
            return DrawerResponse(
                text=RATE_LIMIT_REFUSAL_PLAIN if plain else RATE_LIMIT_REFUSAL_FULL,
                kind="refusal",
                persona=not plain,
            )

        # 3. Generate (buffered — NEVER streamed raw to the client).
        raw = self._respond(user, message, persona_system_prompt(mode))

        # 4. Firewall the output before it is rendered.
        verdict = screen_output(raw, plain=plain)
        if verdict.blocked:
            return DrawerResponse(
                text=verdict.safe_text,
                kind="redirect",
                persona=not plain,
                blocked=True,
                meta={"reason": verdict.reason},
            )

        return DrawerResponse(text=raw, kind="message", persona=not plain)
