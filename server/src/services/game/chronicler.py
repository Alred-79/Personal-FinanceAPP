"""The Weekly Saga Chapter pipeline (v4 §8.1, §8.4).

Law 2 is the spine of this file: the ENGINE computes every number (the fact
sheet), the LLM only renders voice over it, and NO LLM output ever feeds engine
state. The chapter body may contain NO digits — every number is templated in by
the app from the fact sheet. Validators reject bad model output (retry once, then
a deterministic template fallback). Every chapter ends in exactly ONE action.

Determinism: ``build_week_fact_sheet`` returns a byte-identical dict (sorted
keys) for the same inputs — it is the cache key input.
"""

from __future__ import annotations

import logging

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import LlmCache
from ...models import UserInDB
from .canon import render_canon
from .events import GameEventDraft, record_events, register_event_type
from .firewall import screen_output

log = logging.getLogger(__name__)

register_event_type("ChapterGenerated", 1)

TEMPLATE_VERSION = "v1"
MODEL_NAME = "llama-3.3-70b-versatile"  # the flavor model; recorded in the cache key

# Closed archetype enum the engine offers; the LLM picks ONE. An off-enum value
# fails validation (we fall back), it never reaches the card.
ARCHETYPES: dict[str, str] = {
    "patient_sieger": "The Patient Sieger",
    "quiet_builder": "The Quiet Builder",
    "storm_weatherer": "The Storm-Weatherer",
    "steady_hand": "The Steady Hand",
    "comeback": "The Comeback",
}

BODY_MIN_WORDS = 120
BODY_MAX_WORDS = 280

# The single tappable action that terminates every chapter. Always present.
DEFAULT_ACTION = {"kind": "confirm_forecast", "label": "Confirm the forecast", "deep_link": "/forecast"}


# ── the deterministic fact sheet ────────────────────────────────────────────


def build_week_fact_sheet(
    db: Session, user: UserInDB, week_start: date, week_end: date
) -> dict:
    """Compute the week's facts — ENGINE ONLY. Byte-identical for fixed inputs.

    Numbers are buckets/directions, not raw cents (unless whole dollars). The
    streak uses the package-05 enum and never says 'broken'. The Grace episode is
    surfaced as 'a hard stretch weathered' — the trigger is never named.
    """
    from .daily import streak_view
    from .stats import player_xp

    streak = streak_view(db)
    xp = player_xp(db)

    # Boss activity this week: count damage + phase events. (Read-only.)
    from ...db.models import GameEvent

    dmg = db.execute(
        select(GameEvent).where(GameEvent.type == "BossDamaged")
    ).scalars().all()
    phases = db.execute(
        select(GameEvent).where(GameEvent.type == "BossPhaseBroken")
    ).scalars().all()

    # The one action: engine-selected highest-value move (here: the default;
    # later refinement can pull from 03 alert/graduation candidates).
    action = select_one_action(db, user, week_end)

    sheet = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "streak_status": streak["status"],  # never 'broken'
        "streak_current": streak["current"],
        "streak_best": streak["best"],
        "boss_damage_count": len(dmg),
        "boss_phase_count": len(phases),
        "xp_gained": xp["xp"],
        "weathered_hard_stretch": _weathered_grace(db),
        "action": action,
    }
    return _sorted(sheet)


def _sorted(obj: dict) -> dict:
    """Recursively sort dict keys so JSON is byte-identical."""

    def go(o):
        if isinstance(o, dict):
            return {k: go(o[k]) for k in sorted(o)}
        if isinstance(o, list):
            return [go(x) for x in o]
        return o

    return go(obj)


def _weathered_grace(db: Session) -> bool:
    from ...db.models import GameEvent

    return db.execute(
        select(GameEvent).where(GameEvent.type == "GraceApplied").limit(1)
    ).first() is not None


def select_one_action(db: Session, user: UserInDB, as_of: date) -> dict:
    """The engine's single highest-value tappable action for the chapter.

    There is ALWAYS one (test 13): if no alert/graduation candidate exists, the
    confirm-forecast verb is the floor — never zero, never two.
    """
    # Prefer a live alert with a one-tap fix (03). Fall back to confirm_forecast.
    try:
        from .alerts import AlertEngine

        alerts = AlertEngine(db).evaluate(user, as_of)
        for alert in alerts:
            if alert.fix is not None:
                return {
                    "kind": alert.fix.kind,
                    "label": alert.fix.label,
                    "deep_link": f"/alerts/{alert.type}",
                }
    except Exception:
        log.warning("chronicler one-tap action lookup failed; using default", exc_info=True)
    return dict(DEFAULT_ACTION)


# ── cache ───────────────────────────────────────────────────────────────────


def fact_sheet_cache_key(fact_sheet: dict, mode: str) -> str:
    fs_hash = hashlib.sha256(
        json.dumps(fact_sheet, sort_keys=True).encode()
    ).hexdigest()
    raw = f"{MODEL_NAME}|{TEMPLATE_VERSION}|{fs_hash}|{mode}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── validators ──────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""


def validate_chapter(chapter: dict, fact_sheet: dict, canon_text: str) -> ValidationResult:
    """Reject bad model output. Order matters: schema → archetype → words →
    digits → entities → firewall."""
    if not isinstance(chapter, dict):
        return ValidationResult(False, "not_an_object")
    if set(chapter.keys()) < {"title", "body", "archetype_key"}:
        return ValidationResult(False, "schema_missing_keys")

    archetype = chapter.get("archetype_key")
    if archetype not in ARCHETYPES:
        return ValidationResult(False, f"off_enum_archetype:{archetype}")

    body = chapter.get("body", "")
    words = len(body.split())
    if not (BODY_MIN_WORDS <= words <= BODY_MAX_WORDS):
        return ValidationResult(False, f"word_count:{words}")

    # Digit rule: the body may contain NO digits at all (every number is
    # templated in by the app from the fact sheet).
    if any(ch.isdigit() for ch in body):
        return ValidationResult(False, "body_contains_digit")

    # Entity allowlist: every capitalized proper noun must appear in the fact
    # sheet or canon (token match) — no "as Gandalf says". A capitalized word at
    # the START of a sentence is just normal capitalization, not a proper noun,
    # so only MID-SENTENCE capitals are treated as entities.
    allowed = _allowed_tokens(fact_sheet, canon_text)
    for token in _mid_sentence_caps(body):
        if token.lower() in _COMMON_CAPS:
            continue
        if token.lower() not in allowed:
            return ValidationResult(False, f"unknown_entity:{token}")

    # Firewall: advice/neediness/shame in an otherwise-valid chapter.
    verdict = screen_output(body)
    if verdict.blocked:
        return ValidationResult(False, f"firewall:{verdict.reason}")

    return ValidationResult(True)


# Capitalized words that are fine sentence-initially / common English, so they
# don't trip the entity allowlist.
_COMMON_CAPS = {
    "the", "a", "an", "this", "that", "they", "you", "your", "keeper", "it",
    "in", "on", "with", "and", "but", "for", "by", "of", "to", "as", "at",
    "when", "then", "now", "still", "no", "yet", "so", "though", "while",
    "after", "before", "each", "every", "all", "one", "another", "week",
    "day", "days", "month", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "i", "we", "he", "she", "there", "here",
    "her", "his", "their", "its",
}


def _allowed_tokens(fact_sheet: dict, canon_text: str) -> set[str]:
    text = json.dumps(fact_sheet) + " " + canon_text
    return {t.lower() for t in re.findall(r"\b[A-Za-z]+\b", text)}


def _mid_sentence_caps(body: str) -> list[str]:
    """Capitalized words that are NOT the first word of a sentence — i.e. genuine
    proper-noun candidates. A word is sentence-initial if it begins the body or
    follows a sentence terminator (. ! ? :) and optional quotes/space."""
    out: list[str] = []
    # Split into sentences on terminators; within each sentence, every capitalized
    # word EXCEPT the first is a mid-sentence capital.
    for sentence in re.split(r"(?<=[.!?:])\s+", body.strip()):
        words = re.findall(r"\b[A-Za-z]+\b", sentence)
        for w in words[1:]:  # skip the sentence-initial word
            if w[:1].isupper():
                out.append(w)
    return out


# ── template fallback (fully deterministic, no LLM) ─────────────────────────


def template_chapter(fact_sheet: dict) -> dict:
    """A deterministic chapter built only from the fact sheet — no LLM, no
    digits in prose (numbers are templated by the surface), always valid, always
    one action. The product degrades to this when Groq is down or validation
    fails twice."""
    status = fact_sheet["streak_status"]
    streak_clause = {
        "active": "the run holds, day after day",
        "rebuilding": "the line is being rebuilt, patient and unbowed",
        "reviving": "an old run claws its way back",
    }.get(status, "the watch continues")
    weathered = (
        " A hard stretch was weathered, and the ledger still stands."
        if fact_sheet.get("weathered_hard_stretch")
        else ""
    )
    body = (
        "Another week closes in the ledger, and the Keeper kept the watch. "
        f"{streak_clause}. Blows were struck against the standing debt, and the "
        "siege inched a little further toward its end.{weathered} There was no "
        "grand spectacle this week — no trumpets, no fireworks at the gates — "
        "only the steady arithmetic of someone who shows up and does the quiet "
        "work that nobody applauds. That is the kind of progress that lasts. "
        "The monsters prefer a loud, dramatic enemy they can frighten; what "
        "unsettles them is a Keeper who simply returns, day after day, and adds "
        "one more durable line to the chronicle. The saga is written in "
        "consistency rather than in spectacle. This week added its small, "
        "stubborn entry, and the standing debt is a little smaller for it. "
        "The work continues, patient and unhurried, and the Keeper still holds "
        "the pen, ready for whatever the next week brings to the walls."
    ).replace("{weathered}", weathered)
    return {
        "title": "A Week in the Ledger",
        "body": body,
        "archetype_key": "quiet_builder",
        "action": fact_sheet["action"],
        "fallback": True,
    }


# ── generation pipeline ─────────────────────────────────────────────────────


def generate_chapter(
    db: Session,
    user: UserInDB,
    week_start: date,
    week_end: date,
    *,
    llm_call: Optional[Callable[[str], str]] = None,
    sealed: bool = True,
) -> dict:
    """Generate (or fetch cached) the week's chapter.

    ``llm_call`` takes the prompt and returns the raw model string (JSON). When
    None or it fails/validates-out twice, the deterministic template is used. The
    result always: ends in exactly one action, has no stray digits in prose, and
    passes the firewall.
    """
    mode = getattr(user, "game_mode", "off")
    fact_sheet = build_week_fact_sheet(db, user, week_start, week_end)
    canon_text = render_canon(db, user)
    cache_key = fact_sheet_cache_key(fact_sheet, mode)

    cached = db.get(LlmCache, cache_key)
    if cached is not None:
        chapter = json.loads(cached.content)
        chapter["action"] = fact_sheet["action"]  # action is always engine-fresh
        return chapter

    chapter = _generate_uncached(db, user, fact_sheet, canon_text, llm_call)

    # Store the chapter (no expiry once the week is sealed; short TTL otherwise).
    db.add(LlmCache(
        cache_key=cache_key,
        kind="saga_chapter",
        content=json.dumps({k: chapter[k] for k in ("title", "body", "archetype_key")}),
        model=MODEL_NAME,
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=None if sealed else _short_ttl(),
    ))
    record_events(db, [GameEventDraft(
        stream="player", type="ChapterGenerated",
        payload={"week_start": week_start.isoformat(), "fallback": chapter.get("fallback", False)},
        idempotency_key=f"chapter:{user.id}:{week_start.isoformat()}",
    )])
    db.flush()
    return chapter


def _generate_uncached(db, user, fact_sheet, canon_text, llm_call) -> dict:
    if llm_call is None:
        return template_chapter(fact_sheet)
    prompt = build_prompt(fact_sheet, canon_text, getattr(user, "game_mode", "off"))
    for _attempt in range(2):  # one retry
        try:
            raw = llm_call(prompt)
            chapter = json.loads(raw)
        except Exception:
            log.warning("chronicler chapter LLM call/parse failed (attempt %s)", _attempt, exc_info=True)
            continue
        result = validate_chapter(chapter, fact_sheet, canon_text)
        if result.ok:
            chapter["action"] = fact_sheet["action"]  # engine attaches the action
            chapter["fallback"] = False
            return chapter
    # Validation failed twice (or the model errored) → deterministic fallback.
    return template_chapter(fact_sheet)


def build_prompt(fact_sheet: dict, canon_text: str, mode: str) -> str:
    """Assemble the chapter prompt: persona + canon + fact sheet + structure
    contract. Kept under the 4k-token budget by construction (small inputs)."""
    register = "roast" if mode == "full" else "gentle"
    return (
        "You are the Chronicler — an antagonist-coach who narrates the user's "
        "(the Keeper's) financial saga. You roast the MONSTERS (debts, overspending), "
        "never the Keeper. You never give advice, never reference financial products, "
        "never use any digit (the app fills numbers in), and use only proper nouns that "
        f"appear in the canon or fact sheet.\n\nRegister: {register}.\n\n"
        f"CANON:\n{canon_text}\n\nFACT SHEET:\n{json.dumps(fact_sheet, sort_keys=True)}\n\n"
        "Return ONLY JSON: {\"title\": str, \"body\": str (120-280 words, NO digits), "
        "\"archetype_key\": one of " + json.dumps(sorted(ARCHETYPES)) + "}."
    )


def _short_ttl() -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
