"""One-off backfill: emit a ``BackfillSnapshot`` per stream capturing current
derived state, so projections have a starting point without fabricating
per-transaction history.

We NEVER synthesize a fake event stream from existing rows — that would invent
financial history. Instead we snapshot the *derived* state (e.g. last posted
txn per account) as a single ``BackfillSnapshot.v1`` event per stream, keyed by
``backfill:<stream>`` so running it twice is a no-op.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import Account as AccountORM, Expense as ExpenseORM
from .events import GameEventDraft, record_events

logger = logging.getLogger(__name__)


def _player_snapshot(session: Session) -> dict:
    """Derived player-stream state. Package 01 has no stats yet, so this is a
    minimal, stable snapshot — later packages enrich it."""
    return {"note": "player baseline at backfill", "xp": 0}


def _sync_snapshot(session: Session) -> dict:
    """Derived sync-stream state: last posted Plaid txn per account."""
    accounts = session.execute(select(AccountORM.id)).scalars().all()
    per_account: dict[str, dict] = {}
    for account_id in accounts:
        last = session.execute(
            select(ExpenseORM.plaid_transaction_id, ExpenseORM.date)
            .where(
                ExpenseORM.account_id == account_id,
                ExpenseORM.plaid_transaction_id.is_not(None),
            )
            .order_by(ExpenseORM.date.desc())
            .limit(1)
        ).first()
        if last is not None:
            per_account[str(account_id)] = {
                "last_posted_txn_id": last[0],
                "last_posted_date": last[1],
            }
    return {"accounts": per_account}


def run_backfill(session: Session) -> list:
    """Emit one ``BackfillSnapshot`` per stream (``player``, ``sync``).

    Idempotent: keyed by ``backfill:<stream>`` so a second run inserts nothing.
    Returns the resulting events (existing rows on a repeat run).
    """
    drafts = [
        GameEventDraft(
            stream="player",
            type="BackfillSnapshot",
            payload=_player_snapshot(session),
            idempotency_key="backfill:player",
        ),
        GameEventDraft(
            stream="sync",
            type="BackfillSnapshot",
            payload=_sync_snapshot(session),
            idempotency_key="backfill:sync",
        ),
    ]
    return record_events(session, drafts)


def _main() -> int:
    logging.basicConfig(level=logging.INFO)
    from ...db.session import SessionLocal

    session = SessionLocal()
    try:
        events = run_backfill(session)
        session.commit()
        for e in events:
            print(f"backfill stream={e.stream} seq={e.seq} id={e.id}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
