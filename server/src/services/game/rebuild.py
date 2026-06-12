"""Rebuild a projection from scratch by replaying the event log.

A rebuild is the proof that projections are pure functions of the log: truncate
the projection's rows, replay every ``game_events`` row in ``id`` order through
the upcasters + folds, advance the watermark, and flip status back to ``live``.
Same log in → byte-identical projection out, whether built live or rebuilt.

Run as a module:

    python -m server.src.services.game.rebuild <projection>
    python -m server.src.services.game.rebuild --all
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import GameEvent, ProjectionMeta
from . import folds as folds_mod
from .upcasters import upcast

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_status(session: Session, projection: str, status: str) -> ProjectionMeta:
    meta = session.get(ProjectionMeta, projection)
    if meta is None:
        meta = ProjectionMeta(name=projection, last_event_id=0, status=status)
        session.add(meta)
    else:
        meta.status = status
    session.flush()
    return meta


def rebuild_projection(session: Session, projection: str) -> int:
    """Rebuild one projection. Returns the watermark (max folded event id).

    Status round-trips ``rebuilding`` → ``live``. The caller owns the
    transaction; this flushes but does not commit.
    """
    folds_mod.register_builtin_folds()

    meta = _set_status(session, projection, "rebuilding")
    # Truncate this projection's stored rows.
    folds_mod.kv_clear(session, projection)

    # Replay every event whose type feeds this projection, in id order.
    last_id = 0
    events = (
        session.execute(select(GameEvent).order_by(GameEvent.id)).scalars().all()
    )
    for event in events:
        handlers = folds_mod.folds_for(event.type)
        relevant = [h for (p, h) in handlers if p == projection]
        if not relevant:
            # Still advance the watermark past events this projection skips, so
            # last_event_id matches the live-fold watermark (which is the max id
            # of the batch, not the max relevant id).
            last_id = max(last_id, event.id)
            continue
        payload = upcast(event.type, event.v, json.loads(event.payload))
        meta_obj = folds_mod.EventMeta(
            id=event.id,
            stream=event.stream,
            seq=event.seq,
            type=event.type,
            v=event.v,
            caused_by=event.caused_by,
        )
        for handler in relevant:
            try:
                handler(session, payload, meta_obj)
            except Exception:  # noqa: BLE001 — best-effort game layer
                logger.exception(
                    "rebuild fold failed: projection=%s event_id=%s",
                    projection,
                    event.id,
                )
        last_id = max(last_id, event.id)

    meta.last_event_id = last_id
    meta.rebuilt_at = _utcnow_iso()
    meta.status = "live"
    session.flush()
    return last_id


def rebuild_all(session: Session) -> dict[str, int]:
    """Rebuild every registered projection. Returns ``{projection: watermark}``.
    """
    folds_mod.register_builtin_folds()
    result: dict[str, int] = {}
    for projection in sorted(folds_mod.projections()):
        result[projection] = rebuild_projection(session, projection)
    return result


def _main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    if not argv:
        print(
            "usage: python -m server.src.services.game.rebuild "
            "<projection>|--all",
            file=sys.stderr,
        )
        return 2

    # Import here so the module is importable in tests without a live DB.
    from ...db.session import SessionLocal

    folds_mod.register_builtin_folds()
    session = SessionLocal()
    try:
        if argv[0] == "--all":
            result = rebuild_all(session)
            for name, watermark in result.items():
                print(f"rebuilt {name}: watermark={watermark}")
        else:
            watermark = rebuild_projection(session, argv[0])
            print(f"rebuilt {argv[0]}: watermark={watermark}")
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
