"""The canon file — durable saga facts (v4 §7.4, task 1).

Written ONLY by engine code (event subscriptions / settings), never by the LLM.
``render_canon`` produces a ~500-token budget string that goes into the chapter
and drawer prompts; beyond budget it truncates oldest-first so the most recent
saga beats survive.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import CanonFact
from ...models import UserInDB

# ~500-token render budget. We approximate 4 chars/token and cap the rendered
# string; truncation is oldest-first (least recent updated_at dropped).
CANON_RENDER_CHAR_BUDGET = 2000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_fact(
    db: Session,
    user_id: int,
    key: str,
    value: str,
    *,
    source_event_id: int | None = None,
) -> CanonFact:
    """Upsert a canon fact. ENGINE ONLY — never call this from an LLM path."""
    fact = db.execute(
        select(CanonFact).where(
            CanonFact.user_id == user_id, CanonFact.key == key
        )
    ).scalar_one_or_none()
    if fact is None:
        fact = CanonFact(
            user_id=user_id,
            key=key,
            value=value,
            updated_at=_now_iso(),
            source_event_id=source_event_id,
        )
        db.add(fact)
    else:
        fact.value = value
        fact.updated_at = _now_iso()
        fact.source_event_id = source_event_id
    db.flush()
    return fact


def get_facts(db: Session, user_id: int) -> list[CanonFact]:
    return list(
        db.execute(
            select(CanonFact)
            .where(CanonFact.user_id == user_id)
            .order_by(CanonFact.updated_at.desc())
        ).scalars()
    )


def render_canon(db: Session, user: UserInDB) -> str:
    """Render the canon to a budgeted string for prompt inclusion.

    Most-recent-first; truncates oldest beyond the char budget so the prompt
    never blows the token limit. Deterministic for a fixed DB state.
    """
    facts = get_facts(db, user.id)
    lines: list[str] = []
    used = 0
    for fact in facts:  # already most-recent-first
        line = f"- {fact.key}: {fact.value}"
        if used + len(line) + 1 > CANON_RENDER_CHAR_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return "(no canon yet — the saga is just beginning)"
    return "\n".join(lines)


# ── engine subscriptions: the only writers ─────────────────────────────────


def record_boss_defeated(db: Session, user_id: int, boss_name: str, event_id: int | None = None) -> None:
    """Boss defeated → add to the roster of vanquished foes."""
    existing = db.execute(
        select(CanonFact).where(
            CanonFact.user_id == user_id, CanonFact.key == "roster"
        )
    ).scalar_one_or_none()
    roster = []
    if existing and existing.value:
        roster = [r for r in existing.value.split("|") if r]
    if boss_name not in roster:
        roster.append(boss_name)
    set_fact(db, user_id, "roster", "|".join(roster), source_event_id=event_id)


def record_streak_best(db: Session, user_id: int, best: int) -> None:
    set_fact(db, user_id, "streak_best", str(best))


def record_persona_pref(db: Session, user_id: int, register: str) -> None:
    """User persona preference from settings: 'gentle' (default) | 'roast'."""
    set_fact(db, user_id, "persona_register", register)
