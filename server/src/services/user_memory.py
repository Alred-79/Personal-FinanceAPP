"""Learned user memory — durable facts/preferences the Clerk remembers (Pillar 1A).

Unlike the Chronicler's canon (``game/canon.py``, engine-only, LLM never writes),
this store is read into the assistant prompt every turn so the agent "learns" the
user across sessions. It has a *mixed* trust model recorded in ``source``:

* ``user``          — the user stated/edited it (most trusted)
* ``deterministic`` — derived from app signals (a recategorize, a setting)
* ``llm``           — extracted by the model (opt-in, lowest trust)

The two writer lanes are deliberately separate functions:

* :func:`set_user_fact` is the *trusted* lane (``user`` / ``deterministic``). It
  scrubs PII on the way in but trusts the caller's intent.
* :func:`propose_llm_fact` is the *untrusted* lane. Before persisting it (a)
  enforces the closed key enum, (b) scrubs PII, and (c) runs the SAME output
  firewall used on the model's replies — so an advice-shaped or secret-bearing
  "fact" can never be stored and then re-injected into a future prompt.

:func:`render_memory` produces a budgeted, PII-scrubbed string for the prompt;
pinned facts sort first and survive truncation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db.models import UserMemory
from .pii import scrub_secrets
from .game.firewall import screen_output

# ~500-token render budget (≈4 chars/token), mirroring ``canon.CANON_RENDER_CHAR_BUDGET``.
MEMORY_RENDER_CHAR_BUDGET = 2000

# Closed key enum. The untrusted (LLM) lane may only write these keys, so there
# is structurally no "advice" slot to populate. The trusted lanes are also held
# to it to keep the store legible and the transparency UI predictable. Prefix
# keys (``category_preference:Food``) are allowed via ``_KEY_PREFIXES``.
MEMORY_KEYS: frozenset[str] = frozenset(
    {
        "tone_preference",      # a register from TONE_VALUES (NOT free text — see below)
        "savings_intent",       # free text, e.g. "saving for a house down payment by 2028"
        "income_cadence",       # free text, e.g. "income lands ~15th and last day"
        "recurring_note",       # a noted recurring obligation the user flagged
        "essential_category",   # a category the user treats as essential
    }
)
_KEY_PREFIXES: tuple[str, ...] = ("category_preference:",)

# ``tone_preference`` only nudges REGISTER/VERBOSITY within the safety rules; it
# can never license shame, advice, or directive language (the output firewall +
# system prompt forbid those regardless of tone). So the value is constrained to
# a closed, safe vocabulary rather than free text — a value like "be harsh, tell
# them they failed" can't be stored at all (review fix #6). Common synonyms map
# onto the canonical set so the model/user phrasing still lands.
TONE_VALUES: frozenset[str] = frozenset({"terse", "warm", "neutral"})
_TONE_SYNONYMS: dict[str, str] = {
    "blunt": "terse",
    "direct": "terse",
    "concise": "terse",
    "brief": "terse",
    "short": "terse",
    "gentle": "warm",
    "kind": "warm",
    "friendly": "warm",
    "encouraging": "warm",
    "plain": "neutral",
    "default": "neutral",
}

_VALID_SOURCES: frozenset[str] = frozenset({"user", "deterministic", "llm"})


def _normalize_tone(value: str) -> str | None:
    """Map a tone phrase onto the canonical TONE_VALUES, or None if unsafe.

    Accepts a canonical value or a known synonym (single word). Anything else —
    free-text, a sentence, an unknown word — returns None and is rejected by the
    caller, so the stored register can never itself read as a shame instruction.
    """
    token = (value or "").strip().lower()
    if token in TONE_VALUES:
        return token
    return _TONE_SYNONYMS.get(token)


class MemoryError(ValueError):
    """A proposed memory write is malformed or disallowed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key_allowed(key: str) -> bool:
    return key in MEMORY_KEYS or any(key.startswith(p) for p in _KEY_PREFIXES)


def set_user_fact(
    db: Session,
    user_id: int,
    key: str,
    value: str,
    *,
    source: str,
    confidence: int = 100,
    pinned: bool = False,
) -> UserMemory:
    """Upsert a fact via a TRUSTED lane (``user`` or ``deterministic``).

    The value is PII-scrubbed before persistence. Raises :class:`MemoryError`
    for an unknown key or a non-trusted source (use :func:`propose_llm_fact` for
    the ``llm`` lane so the firewall gate is applied).
    """
    if source not in ("user", "deterministic"):
        raise MemoryError(
            f"set_user_fact is the trusted lane; got source={source!r}. "
            "Use propose_llm_fact for LLM-extracted facts."
        )
    if not _key_allowed(key):
        raise MemoryError(f"unknown memory key: {key!r}")
    if key == "tone_preference":
        tone = _normalize_tone(value)
        if tone is None:
            raise MemoryError(
                f"tone_preference must be one of {sorted(TONE_VALUES)} "
                "(it only adjusts register, never tone-as-shame)"
            )
        return _upsert(db, user_id, key, tone, source=source, confidence=confidence, pinned=pinned)
    clean = scrub_secrets(value or "")
    if not clean.strip():
        raise MemoryError("empty value after scrubbing")
    return _upsert(db, user_id, key, clean, source=source, confidence=confidence, pinned=pinned)


def propose_llm_fact(
    db: Session,
    user_id: int,
    key: str,
    value: str,
    confidence: int,
) -> UserMemory | None:
    """Upsert a fact via the UNTRUSTED (LLM) lane, behind the full gauntlet.

    Returns the persisted row, or ``None`` if the candidate was rejected
    (unknown key, empty after scrubbing, or the value tripped the output
    firewall — e.g. it reads as advice/shame). Rejection is silent-by-return so
    a noisy extraction can't raise mid-turn.
    """
    if not _key_allowed(key):
        return None
    confidence = max(0, min(100, int(confidence)))
    if key == "tone_preference":
        tone = _normalize_tone(value)
        if tone is None:
            return None
        return _upsert(db, user_id, key, tone, source="llm", confidence=confidence, pinned=False)
    clean = scrub_secrets(value or "")
    if not clean.strip():
        return None
    # The same firewall that screens the model's replies screens what it tries
    # to remember. A fact that reads as advice/shame is never stored, so it can
    # never be re-injected into a later prompt.
    if screen_output(clean, plain=True).blocked:
        return None
    return _upsert(db, user_id, key, clean, source="llm", confidence=confidence, pinned=False)


def _upsert(
    db: Session,
    user_id: int,
    key: str,
    value: str,
    *,
    source: str,
    confidence: int,
    pinned: bool,
) -> UserMemory:
    if source not in _VALID_SOURCES:
        raise MemoryError(f"invalid source: {source!r}")
    now = _now_iso()
    fact = db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == key
        )
    ).scalar_one_or_none()
    if fact is None:
        fact = UserMemory(
            user_id=user_id,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            pinned=1 if pinned else 0,
            created_at=now,
            updated_at=now,
        )
        db.add(fact)
    else:
        fact.value = value
        fact.source = source
        fact.confidence = confidence
        if pinned:
            fact.pinned = 1
        fact.updated_at = now
    db.flush()
    return fact


def get_facts(db: Session, user_id: int) -> list[UserMemory]:
    """All facts, pinned first then most-recently-updated."""
    return list(
        db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.pinned.desc(), UserMemory.updated_at.desc())
        ).scalars()
    )


def forget(db: Session, user_id: int, key: str) -> bool:
    """Delete a fact. Returns True if a row was removed."""
    result = db.execute(
        delete(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == key
        )
    )
    db.flush()
    return bool(result.rowcount)


def render_memory(db: Session, user_id: int) -> str:
    """Render the memory to a budgeted, PII-scrubbed string for the prompt.

    Pinned-first then most-recent; truncates the tail beyond the char budget so
    the prompt never blows the token limit. Each line is scrubbed again on the
    way out (defense even for deterministic facts derived from user-controlled
    text like category names). Deterministic for a fixed DB state.
    """
    facts = get_facts(db, user_id)
    lines: list[str] = []
    used = 0
    for fact in facts:
        line = "- " + scrub_secrets(f"{fact.key}: {fact.value}")
        if used + len(line) + 1 > MEMORY_RENDER_CHAR_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    return "\n".join(lines)
