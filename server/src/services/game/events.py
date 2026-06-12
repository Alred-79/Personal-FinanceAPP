"""``record_events`` — THE single write path into the game event log.

Nothing else inserts into ``game_events`` (a grep test enforces this). The
function:

1. Validates every draft's type against ``EVENT_TYPES`` (typo guard).
2. For each draft, computes the next per-stream ``seq`` (``MAX(seq)+1`` under
   SQLite's single-writer lock — safe), and inserts.
3. Honours ``idempotency_key`` uniqueness: a draft whose key already exists is
   an *ignored* insert — it returns the pre-existing row and runs NO folds
   (replays are free and side-effect-free).
4. Synchronously folds each *newly inserted* event into its projections, in the
   same session/transaction, then advances each touched projection's watermark.

The caller owns the transaction boundary (commit/rollback). On SQLite a single
writer means the read-modify-write of ``seq`` and the fold all happen under one
lock with no interleaving.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import GameEvent, ProjectionMeta
from . import folds as folds_mod
from .upcasters import current_version, upcast

logger = logging.getLogger(__name__)

# The known event types and the version `record_events` stamps on new writes.
# An unknown type is rejected before anything is inserted (typo guard).
EVENT_TYPES: dict[str, int] = {
    "BackfillSnapshot": 1,
    "SyncGapOpened": 1,
    "SyncGapClosed": 1,
    "TxnPosted": 1,
    "TxnCorrected": 1,
    "TxnReversed": 1,
    "MonthSealed": 1,
    "XpAwarded": 1,
}


def register_event_type(name: str, version: int = 1) -> None:
    """Register an additional event type (used by tests for fixture types).

    Later packages add their own types the same way at import time.
    """
    EVENT_TYPES[name] = version


@dataclass
class GameEventDraft:
    """A request to append one event. ``seq``/``id``/``created_at`` are assigned
    by ``record_events`` — the caller never sets them."""

    stream: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    caused_by: Optional[int] = None
    v: Optional[int] = None  # defaults to the registered current version


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_seq(session: Session, stream: str) -> int:
    """The next per-stream sequence number (starts at 1).

    Safe as a plain MAX under SQLite's single-writer model: only one connection
    can be writing, so no two appends to the same stream race here.
    """
    current = session.execute(
        select(func.coalesce(func.max(GameEvent.seq), 0)).where(
            GameEvent.stream == stream
        )
    ).scalar_one()
    return int(current) + 1


def _existing_by_idem(session: Session, key: str) -> Optional[GameEvent]:
    return session.execute(
        select(GameEvent).where(GameEvent.idempotency_key == key)
    ).scalar_one_or_none()


def record_events(
    session: Session, drafts: list[GameEventDraft]
) -> list[GameEvent]:
    """Append ``drafts`` and synchronously fold the newly-inserted ones.

    Returns one ``GameEvent`` per draft, in order — the freshly inserted row, or
    the pre-existing row when the idempotency key collided. Raises ``ValueError``
    on an unknown event type, inserting nothing.
    """
    # Ensure all builtin folds AND the event types they own are registered
    # before we validate. Under the cold (events-first) import order, the XP
    # module that registers AllocationMade/BillPaidOnTime/… into EVENT_TYPES is
    # only loaded here (via register_builtin_folds → stats → xp), so this must
    # run before the typo guard or those types would read as "unknown".
    folds_mod.register_builtin_folds()

    # Typo guard up front — reject the whole batch before any insert so a bad
    # draft can't leave a half-written batch.
    for d in drafts:
        if d.type not in EVENT_TYPES:
            raise ValueError(f"unknown game event type: {d.type!r}")

    results: list[GameEvent] = []
    newly_inserted: list[GameEvent] = []

    for d in drafts:
        if d.idempotency_key is not None:
            existing = _existing_by_idem(session, d.idempotency_key)
            if existing is not None:
                # Ignored insert: return the prior row, emit nothing downstream.
                results.append(existing)
                continue

        version = d.v if d.v is not None else current_version(d.type)
        event = GameEvent(
            stream=d.stream,
            seq=_next_seq(session, d.stream),
            type=d.type,
            v=version,
            payload=json.dumps(d.payload, sort_keys=True),
            idempotency_key=d.idempotency_key,
            caused_by=d.caused_by,
            created_at=_utcnow_iso(),
        )
        session.add(event)
        # Flush so the event gets its id (needed for caused_by chains and the
        # fold meta) without committing — the caller still owns the transaction.
        session.flush()
        results.append(event)
        newly_inserted.append(event)

    # Fold only the newly inserted events, in id order, same transaction.
    for event in sorted(newly_inserted, key=lambda e: e.id):
        payload = upcast(event.type, event.v, json.loads(event.payload))
        meta = folds_mod.EventMeta(
            id=event.id,
            stream=event.stream,
            seq=event.seq,
            type=event.type,
            v=event.v,
            caused_by=event.caused_by,
        )
        folds_mod.apply_folds(session, payload, meta)

    # Advance the watermark of EVERY registered projection to the batch max — not
    # just the projections this batch touched. A watermark means "every event up
    # to this id has been considered", and an event a projection ignores is still
    # considered (and skipped). Rebuild advances every projection to the global
    # max the same way (rebuild.py), so bumping only touched projections here
    # would make live and rebuilt watermarks diverge — breaking package 01's
    # determinism contract (a batch that touches only player_state must still
    # advance sync_state's watermark past those event ids).
    if newly_inserted:
        max_id = max(e.id for e in newly_inserted)
        for projection_name in folds_mod.projections():
            _bump_watermark(session, projection_name, max_id)

    return results


def _bump_watermark(session: Session, projection: str, event_id: int) -> None:
    meta = session.get(ProjectionMeta, projection)
    if meta is None:
        meta = ProjectionMeta(
            name=projection, last_event_id=event_id, status="live"
        )
        session.add(meta)
    elif event_id > meta.last_event_id:
        meta.last_event_id = event_id
