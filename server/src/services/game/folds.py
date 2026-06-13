"""The fold registry and the projections that fold over the event log.

A *fold* is a pure-ish handler ``(session, event_payload, event_meta) -> None``
that advances a projection's state in response to one event. Folds run
synchronously inside the same transaction that appended the event (see
``events.record_events``) and again, in id order, during a rebuild
(``rebuild.py``). The same handler must produce the same projection whether it
runs live or replayed — so a fold computes only from the event payload (and the
projection's own current row), never from financial-truth tables or wall-clock
time.

Package 01 ships one real projection, ``sync_state``, which proves the
machinery: it tracks the last posted transaction per account and the set of
open sync gaps.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventMeta:
    """The non-payload fields a fold may need: identity and ordering."""

    id: int
    stream: str
    seq: int
    type: str
    v: int
    caused_by: int | None


# event type -> list of (projection_name, handler). One event may feed several
# projections; one projection may react to several types.
FoldHandler = Callable[[Session, dict, EventMeta], None]
_FOLDS: dict[str, list[tuple[str, FoldHandler]]] = {}

# Every projection that has at least one registered fold. Used by rebuild --all
# and by the watermark bookkeeping.
_PROJECTIONS: set[str] = set()


def register_fold(
    projection_name: str, event_type: str, handler: FoldHandler
) -> None:
    """Register ``handler`` to advance ``projection_name`` on ``event_type``."""
    _FOLDS.setdefault(event_type, []).append((projection_name, handler))
    _PROJECTIONS.add(projection_name)


def projections() -> set[str]:
    """All projection names that have at least one registered fold."""
    return set(_PROJECTIONS)


def folds_for(event_type: str) -> list[tuple[str, FoldHandler]]:
    """Registered ``(projection, handler)`` pairs for ``event_type`` (may be []).
    """
    return list(_FOLDS.get(event_type, []))


def apply_folds(session: Session, payload: dict, meta: EventMeta) -> None:
    """Run every fold registered for ``meta.type``.

    A fold that raises is logged and skipped — the game layer is best-effort and
    must never break the finance request path (guardrail, package 01). The event
    row itself is already committed by the caller; a failed fold just leaves that
    projection slightly behind until the next rebuild.

    Step 09 — fold-failure VISIBILITY. The watermark still advances exactly as
    before (events.py owns that, and the determinism contract requires it). What
    was missing was any signal that a projection silently desynced. So on a raise
    we ALSO record a per-projection ``_health`` marker (best-effort, never raises
    into the finance path) so ``/game/health/`` and a rebuild trigger can see it.
    """
    for projection_name, handler in folds_for(meta.type):
        try:
            handler(session, payload, meta)
        except Exception:  # noqa: BLE001 — best-effort game layer
            logger.exception(
                "fold failed: projection=%s type=%s event_id=%s",
                projection_name,
                meta.type,
                meta.id,
            )
            _mark_behind(session, projection_name, meta.id)


# ---------------------------------------------------------------------------
# Fold-failure health markers (Step 09)
#
# A failed fold does NOT hold the watermark back (that would break the
# determinism contract — see events.py). Instead it records a marker in its own
# ``_HEALTH`` KV namespace so the desync is detectable and a rebuild can be
# triggered. The marker is keyed by projection name and clears on a successful
# rebuild. The marker write is itself best-effort: it must NEVER raise into the
# finance request path (guardrail, package 01).
# ---------------------------------------------------------------------------

_HEALTH = "_health"


def _mark_behind(session: Session, projection: str, event_id: int) -> None:
    """Record/extend a projection's failure marker. Best-effort, never raises."""
    try:
        existing = kv_get(session, _HEALTH, projection) or {}
        marker = {
            "projection": projection,
            "behind_since_event": existing.get("behind_since_event", event_id),
            "last_error_event": event_id,
            "count": int(existing.get("count", 0)) + 1,
        }
        kv_put(session, _HEALTH, projection, marker)
    except Exception:  # noqa: BLE001 — health bookkeeping must never break finance
        logger.exception(
            "failed to record fold-failure marker: projection=%s event_id=%s",
            projection,
            event_id,
        )


def health_markers(session: Session) -> list[dict]:
    """Every open fold-failure marker (one per behind projection). Empty when
    all projections are healthy. Read-only; safe to call anytime."""
    try:
        ensure_kv(session)
        rows = session.execute(
            text(
                "SELECT value FROM game_projection_kv WHERE projection = :p "
                "ORDER BY key"
            ),
            {"p": _HEALTH},
        ).scalars().all()
        return [json.loads(r) for r in rows]
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        logger.exception("failed to read fold-failure markers")
        return []


def clear_behind(session: Session, projection: str) -> None:
    """Clear a projection's failure marker (called after a successful rebuild)."""
    ensure_kv(session)
    session.execute(
        text(
            "DELETE FROM game_projection_kv WHERE projection = :h AND key = :k"
        ),
        {"h": _HEALTH, "k": projection},
    )


# ---------------------------------------------------------------------------
# Projection storage helpers
#
# Projections live in lightweight key/value rows so package 01 needs no extra
# migration per projection — later packages can graduate hot projections to
# real tables. We use a single ``game_projection_kv`` table created on demand by
# create_all/migration? No — to avoid an extra migration we store sync_state in
# projection_meta-adjacent rows. Simpler: keep the projection in its own table
# defined alongside the others. For package 01 we use a tiny generic KV created
# here lazily via SQL so the substrate stays self-contained.
# ---------------------------------------------------------------------------

_KV_DDL = (
    "CREATE TABLE IF NOT EXISTS game_projection_kv ("
    "  projection VARCHAR NOT NULL,"
    "  key VARCHAR NOT NULL,"
    "  value TEXT NOT NULL,"
    "  PRIMARY KEY (projection, key)"
    ")"
)


def ensure_kv(session: Session) -> None:
    """Create the generic projection KV table if it doesn't exist."""
    session.execute(text(_KV_DDL))


def kv_get(session: Session, projection: str, key: str) -> dict | None:
    ensure_kv(session)
    row = session.execute(
        text(
            "SELECT value FROM game_projection_kv "
            "WHERE projection = :p AND key = :k"
        ),
        {"p": projection, "k": key},
    ).scalar_one_or_none()
    return json.loads(row) if row is not None else None


def kv_put(session: Session, projection: str, key: str, value: dict) -> None:
    ensure_kv(session)
    session.execute(
        text(
            "INSERT INTO game_projection_kv (projection, key, value) "
            "VALUES (:p, :k, :v) "
            "ON CONFLICT(projection, key) DO UPDATE SET value = excluded.value"
        ),
        {"p": projection, "k": key, "v": json.dumps(value, sort_keys=True)},
    )


def kv_clear(session: Session, projection: str) -> None:
    """Drop all rows for a projection (used at the start of a rebuild)."""
    ensure_kv(session)
    session.execute(
        text("DELETE FROM game_projection_kv WHERE projection = :p"),
        {"p": projection},
    )


# ---------------------------------------------------------------------------
# Projection: sync_state
#
# Tracks, per account: the last posted Plaid transaction (id + date), and the
# list of currently-open sync gaps. Open gaps matter to later packages (in-gap
# days are treated leniently). Stored under keys:
#   "account:<id>"  -> {"last_posted_txn_id": str, "last_posted_date": str}
#   "gaps"          -> {"open": [{account_id, opened_at, ...}], "closed": [...]}
# ---------------------------------------------------------------------------

SYNC_STATE = "sync_state"


def _fold_txn_posted(session: Session, payload: dict, meta: EventMeta) -> None:
    account_id = payload.get("account_id")
    if account_id is None:
        return
    key = f"account:{account_id}"
    kv_put(
        session,
        SYNC_STATE,
        key,
        {
            "last_posted_txn_id": payload.get("plaid_transaction_id"),
            "last_posted_date": payload.get("date"),
        },
    )


def _fold_gap_opened(session: Session, payload: dict, meta: EventMeta) -> None:
    state = kv_get(session, SYNC_STATE, "gaps") or {"open": [], "closed": []}
    state["open"].append(
        {
            "account_id": payload.get("account_id"),
            "opened_at": payload.get("opened_at"),
            "from": payload.get("from"),
            "event_id": meta.id,
        }
    )
    kv_put(session, SYNC_STATE, "gaps", state)


def _fold_gap_closed(session: Session, payload: dict, meta: EventMeta) -> None:
    state = kv_get(session, SYNC_STATE, "gaps") or {"open": [], "closed": []}
    account_id = payload.get("account_id")
    # Close the oldest open gap for this account.
    remaining = []
    closed_one = None
    for gap in state["open"]:
        if closed_one is None and gap.get("account_id") == account_id:
            closed_one = gap
        else:
            remaining.append(gap)
    state["open"] = remaining
    if closed_one is not None:
        state["closed"].append(
            {
                **closed_one,
                "closed_at": payload.get("closed_at"),
                "to": payload.get("to"),
            }
        )
    kv_put(session, SYNC_STATE, "gaps", state)


# ---------------------------------------------------------------------------
# Projection: txn_ledger
#
# A running net per account, folding the full posted/corrected/reversed cycle.
# This is the projection that proves corrections and reversals fold correctly
# (doc test cases 6-7). Stored under key "account:<id>" -> {"net_cents": int}.
#
# A correction applies its signed field_delta (delta, not absolute). A reversal
# subtracts the ORIGINAL amount carried in the event payload — never a value
# read back from current state — so it's correct even if other events have since
# touched the account.
# ---------------------------------------------------------------------------

TXN_LEDGER = "txn_ledger"


def _ledger_get(session: Session, account_id) -> dict:
    return kv_get(session, TXN_LEDGER, f"account:{account_id}") or {"net_cents": 0}


def _ledger_put(session: Session, account_id, state: dict) -> None:
    kv_put(session, TXN_LEDGER, f"account:{account_id}", state)


def _fold_ledger_posted(session: Session, payload: dict, meta: EventMeta) -> None:
    account_id = payload.get("account_id")
    if account_id is None:
        return
    state = _ledger_get(session, account_id)
    state["net_cents"] = state["net_cents"] + int(payload.get("amount_cents", 0))
    _ledger_put(session, account_id, state)


def _fold_ledger_corrected(
    session: Session, payload: dict, meta: EventMeta
) -> None:
    account_id = payload.get("account_id")
    if account_id is None:
        return
    delta = int(payload.get("field_deltas", {}).get("amount_cents", 0))
    if delta == 0:
        return
    state = _ledger_get(session, account_id)
    state["net_cents"] = state["net_cents"] + delta
    _ledger_put(session, account_id, state)


def _fold_ledger_reversed(
    session: Session, payload: dict, meta: EventMeta
) -> None:
    account_id = payload.get("account_id")
    if account_id is None:
        return
    # Compensate using the ORIGINAL amount from the event payload, not state.
    original = int(payload.get("original_amount_cents", 0))
    state = _ledger_get(session, account_id)
    state["net_cents"] = state["net_cents"] - original
    _ledger_put(session, account_id, state)


def register_builtin_folds() -> None:
    """Register every fold the substrate ships with (idempotent).

    Two registration groups, guarded INDEPENDENTLY so a failure to load one
    can't strand the other:

    * the sync/ledger folds defined in this module, and
    * the ``player_state`` XP folds, which live in ``stats.py``.

    The XP folds import ``stats`` → ``xp`` → ``events``. When *this module* is
    first imported as part of ``events.py``'s own import (events.py does
    ``from . import folds``), that chain is circular: ``events`` is only
    half-initialised, so importing ``stats`` raises. We must NOT let that abort
    builtin-fold registration, AND we must retry the stats import on a later
    call (e.g. the first ``record_events``), by which point ``events`` has
    finished initialising. So the stats registration is OUTSIDE the
    sync-folds-already-present guard, and is itself idempotent.
    """
    # Group 1: sync/ledger folds — guard against double-registration only here.
    if not any(p == SYNC_STATE for ps in _FOLDS.values() for p, _ in ps):
        register_fold(SYNC_STATE, "TxnPosted", _fold_txn_posted)
        register_fold(SYNC_STATE, "SyncGapOpened", _fold_gap_opened)
        register_fold(SYNC_STATE, "SyncGapClosed", _fold_gap_closed)
        register_fold(TXN_LEDGER, "TxnPosted", _fold_ledger_posted)
        register_fold(TXN_LEDGER, "TxnCorrected", _fold_ledger_corrected)
        register_fold(TXN_LEDGER, "TxnReversed", _fold_ledger_reversed)

    # Group 2: player_state XP folds (package 04). Retried every call until it
    # succeeds — under the events.py-first import order the first attempt hits
    # the circular import; a later call (record_events / rebuild) succeeds.
    _register_stat_folds_if_possible()

    # Group 3: streak_state folds (package 05) — same circular-import shape, same
    # retry-until-importable handling.
    _register_daily_folds_if_possible()

    # Group 4: boss_state folds (package 06) — same retry-until-importable shape.
    _register_boss_folds_if_possible()


def _register_stat_folds_if_possible() -> bool:
    """Try to register the stats folds; return True once they're present.

    Idempotent and self-healing: skips immediately once registered, and on the
    circular-import window logs at debug (not error) since a later call recovers.
    """
    if any(p == PLAYER_STATE for ps in _FOLDS.values() for p, _ in ps):
        return True
    try:
        from .stats import register_stat_folds
    except ImportError:
        # Expected once, during events.py's own import (events not yet ready).
        logger.debug("stat folds not yet importable (circular window); will retry")
        return False
    register_stat_folds()
    return True


def _register_daily_folds_if_possible() -> bool:
    """Try to register the streak_state folds; return True once present.

    Same circular-import handling as the stats folds: ``daily`` imports
    ``events``, so under the events-first import order the first attempt raises
    and a later call (record_events / rebuild) succeeds.
    """
    if any(p == STREAK_STATE for ps in _FOLDS.values() for p, _ in ps):
        return True
    try:
        from .daily import register_daily_folds
    except ImportError:
        logger.debug("daily folds not yet importable (circular window); will retry")
        return False
    register_daily_folds()
    return True


def _register_boss_folds_if_possible() -> bool:
    """Try to register the boss_state folds; return True once present. Same
    retry-until-importable shape as the stats/daily groups."""
    if any(p == BOSS_STATE for ps in _FOLDS.values() for p, _ in ps):
        return True
    try:
        from .boss import register_boss_folds
    except ImportError:
        logger.debug("boss folds not yet importable (circular window); will retry")
        return False
    register_boss_folds()
    return True


# Projection names the late-registered folds use (kept in sync with their
# defining modules; duplicated here to avoid importing those modules at load).
PLAYER_STATE = "player_state"  # stats.PLAYER_STATE
STREAK_STATE = "streak_state"  # daily.STREAK_STATE
BOSS_STATE = "boss_state"  # boss.BOSS_STATE


register_builtin_folds()
