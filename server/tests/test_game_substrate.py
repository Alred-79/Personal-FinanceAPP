"""v4 package 01 — event substrate tests (groups 1-9, 13-20).

Covers idempotency/append-only, corrections/clamp, rebuild/determinism, and
integrity/migrations. Sync-fold specifics (pending, gaps) live in
test_game_sync_fold.py.
"""

from __future__ import annotations

import json
import random

import pytest
from sqlalchemy import text

from server.src.db.models import GameEvent, ProjectionMeta, User, Account, Expense
from server.src.services.game import folds as folds_mod
from server.src.services.game import upcasters as upcasters_mod
from server.src.services.game.clamp import clamped_xp_delta
from server.src.services.game.events import (
    GameEventDraft,
    record_events,
    register_event_type,
)
from server.src.services.game.rebuild import rebuild_all, rebuild_projection
from server.tests.integrity import finance_tables_fingerprint


# ── helpers ──────────────────────────────────────────────────────────────


def _ledger_net(session, account_id: int) -> int:
    row = session.execute(
        text(
            "SELECT value FROM game_projection_kv "
            "WHERE projection='txn_ledger' AND key=:k"
        ),
        {"k": f"account:{account_id}"},
    ).scalar_one_or_none()
    return json.loads(row)["net_cents"] if row else 0


def _posted(account_id: int, txn_id: str, amount_cents: int) -> GameEventDraft:
    return GameEventDraft(
        stream="sync",
        type="TxnPosted",
        payload={
            "plaid_transaction_id": txn_id,
            "account_id": account_id,
            "kind": "expense" if amount_cents >= 0 else "income",
            "amount_cents": amount_cents,
            "category": "Other",
            "date": "2026-06-01",
        },
        idempotency_key=f"plaid:{txn_id}:posted",
    )


# ── 1-5: idempotency & append-only ───────────────────────────────────────


def test_duplicate_idempotency_key_inserts_once_and_folds_once(db_session):
    draft = _posted(1, "txn-A", 5000)
    record_events(db_session, [draft])
    db_session.flush()
    assert _ledger_net(db_session, 1) == 5000

    # Same key again → one row total, projection unchanged (fold did not re-run).
    record_events(db_session, [_posted(1, "txn-A", 5000)])
    db_session.flush()
    rows = db_session.execute(
        text("SELECT COUNT(*) FROM game_events WHERE idempotency_key=:k"),
        {"k": "plaid:txn-A:posted"},
    ).scalar_one()
    assert rows == 1
    assert _ledger_net(db_session, 1) == 5000


def test_replaying_a_whole_batch_emits_nothing(db_session):
    batch = [_posted(1, "t1", 1000), _posted(1, "t2", 2000)]
    record_events(db_session, batch)
    db_session.flush()
    before_count = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")
    ).scalar_one()
    before_net = _ledger_net(db_session, 1)

    # Replay identical batch.
    record_events(db_session, [_posted(1, "t1", 1000), _posted(1, "t2", 2000)])
    db_session.flush()
    after_count = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")
    ).scalar_one()
    assert after_count == before_count
    assert _ledger_net(db_session, 1) == before_net


def test_raw_update_and_delete_are_blocked_by_trigger(db_session):
    record_events(db_session, [_posted(1, "t1", 1000)])
    db_session.flush()
    with pytest.raises(Exception):
        db_session.execute(text("UPDATE game_events SET type='X' WHERE id=1"))
        db_session.flush()
    db_session.rollback()
    record_events(db_session, [_posted(1, "t1b", 1000)])
    db_session.flush()
    with pytest.raises(Exception):
        db_session.execute(text("DELETE FROM game_events WHERE id=1"))
        db_session.flush()
    db_session.rollback()


def test_unknown_event_type_raises_and_inserts_nothing(db_session):
    before = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")
    ).scalar_one()
    with pytest.raises(ValueError):
        record_events(
            db_session,
            [GameEventDraft(stream="player", type="NotARealType", payload={})],
        )
    after = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")
    ).scalar_one()
    assert after == before


def test_two_streams_get_contiguous_seq(db_session):
    drafts = [
        GameEventDraft(stream="player", type="XpAwarded", payload={"applied": 1, "true": 1}),
        GameEventDraft(stream="month:2026-06", type="MonthSealed", payload={}),
        GameEventDraft(stream="player", type="XpAwarded", payload={"applied": 2, "true": 2}),
        GameEventDraft(stream="month:2026-06", type="MonthSealed", payload={}, idempotency_key="m2"),
    ]
    record_events(db_session, drafts)
    db_session.flush()
    player_seqs = db_session.execute(
        text("SELECT seq FROM game_events WHERE stream='player' ORDER BY seq")
    ).scalars().all()
    month_seqs = db_session.execute(
        text("SELECT seq FROM game_events WHERE stream='month:2026-06' ORDER BY seq")
    ).scalars().all()
    assert player_seqs == [1, 2]
    assert month_seqs == [1, 2]


# ── 6-9: corrections & clamp ─────────────────────────────────────────────


def test_correction_adjusts_projection_and_links_caused_by(db_session):
    [posted] = record_events(db_session, [_posted(1, "tA", 5000)])
    db_session.flush()
    correction = GameEventDraft(
        stream="sync",
        type="TxnCorrected",
        payload={
            "plaid_transaction_id": "tA",
            "account_id": 1,
            "field_deltas": {"amount_cents": -1000},
        },
        idempotency_key="plaid:tA:corrected:1",
        caused_by=posted.id,
    )
    [corr] = record_events(db_session, [correction])
    db_session.flush()
    assert _ledger_net(db_session, 1) == 4000  # 5000 - 1000
    assert corr.caused_by == posted.id
    # Both events present.
    assert db_session.execute(
        text("SELECT COUNT(*) FROM game_events WHERE type IN ('TxnPosted','TxnCorrected')")
    ).scalar_one() == 2


def test_reversal_compensates_from_original_payload_not_current_state(db_session):
    [posted] = record_events(db_session, [_posted(1, "tA", 5000)])
    db_session.flush()
    # Other events touch the same account AFTER the original — proving the
    # reversal does not read back current state.
    record_events(db_session, [_posted(1, "tB", 3000)])
    db_session.flush()
    assert _ledger_net(db_session, 1) == 8000

    reversal = GameEventDraft(
        stream="sync",
        type="TxnReversed",
        payload={
            "plaid_transaction_id": "tA",
            "account_id": 1,
            "original_amount_cents": 5000,
        },
        idempotency_key="plaid:tA:reversed",
        caused_by=posted.id,
    )
    record_events(db_session, [reversal])
    db_session.flush()
    # 8000 - 5000 (the ORIGINAL amount) = 3000, i.e. as if tA never happened.
    assert _ledger_net(db_session, 1) == 3000


def test_clamped_xp_delta_is_one_sided():
    assert clamped_xp_delta(-30) == (0, -30)
    assert clamped_xp_delta(10) == (10, 10)
    assert clamped_xp_delta(0) == (0, 0)


def test_negative_xp_correction_leaves_xp_unchanged_but_stores_true(db_session):
    # A fold-style use of the clamp: a negative correction applies 0 but the
    # event payload records both numbers.
    applied, true = clamped_xp_delta(-30)
    draft = GameEventDraft(
        stream="player",
        type="XpAwarded",
        payload={"applied": applied, "true": true, "reason": "correction"},
    )
    [ev] = record_events(db_session, [draft])
    db_session.flush()
    stored = json.loads(ev.payload)
    assert stored["applied"] == 0
    assert stored["true"] == -30


# ── 13-16: rebuild & determinism ─────────────────────────────────────────


def test_rebuild_is_byte_identical_to_live_fold(db_session):
    rng = random.Random(1234)
    types = ["posted", "corrected", "reversed"]
    posted_ids: list[str] = []
    n = 0
    for _ in range(200):
        choice = rng.choice(types)
        account_id = rng.randint(1, 3)
        if choice == "posted" or not posted_ids:
            n += 1
            tid = f"t{n}"
            posted_ids.append(tid)
            record_events(db_session, [_posted(account_id, tid, rng.randint(-9000, 9000))])
        elif choice == "corrected":
            tid = rng.choice(posted_ids)
            record_events(db_session, [GameEventDraft(
                stream="sync", type="TxnCorrected",
                payload={"plaid_transaction_id": tid, "account_id": account_id,
                         "field_deltas": {"amount_cents": rng.randint(-500, 500)}},
            )])
        else:
            tid = rng.choice(posted_ids)
            record_events(db_session, [GameEventDraft(
                stream="sync", type="TxnReversed",
                payload={"plaid_transaction_id": tid, "account_id": account_id,
                         "original_amount_cents": rng.randint(0, 9000)},
            )])
    db_session.flush()
    live = {a: _ledger_net(db_session, a) for a in (1, 2, 3)}

    rebuild_all(db_session)
    db_session.flush()
    rebuilt = {a: _ledger_net(db_session, a) for a in (1, 2, 3)}
    assert live == rebuilt


def test_rebuild_with_registered_upcaster(db_session):
    upcasters_mod._reset_for_tests()
    register_event_type("TestEvt", 1)
    folds_mod.register_fold(
        "test_proj", "TestEvt",
        lambda s, p, m: folds_mod.kv_put(s, "test_proj", "sum",
                                         {"v": (folds_mod.kv_get(s, "test_proj", "sum") or {"v": 0})["v"] + p["amount"]}),
    )
    # Store a v1 payload (uses "amt"); register an upcaster lifting amt->amount.
    record_events(db_session, [GameEventDraft(stream="t", type="TestEvt", payload={"amt": 7}, v=1)])
    db_session.flush()
    upcasters_mod.register_upcaster("TestEvt", 1, lambda p: {"amount": p["amt"]})

    rebuild_projection(db_session, "test_proj")
    db_session.flush()
    got = folds_mod.kv_get(db_session, "test_proj", "sum")
    assert got == {"v": 7}  # upcast amt->amount, fold consumed v2 shape
    # Stored row untouched (still has "amt").
    raw = db_session.execute(
        text("SELECT payload FROM game_events WHERE type='TestEvt'")
    ).scalar_one()
    assert json.loads(raw) == {"amt": 7}
    upcasters_mod._reset_for_tests()
    folds_mod._FOLDS.pop("TestEvt", None)


def test_watermark_tracks_max_folded_id_and_status_round_trips(db_session):
    record_events(db_session, [_posted(1, "t1", 1000), _posted(1, "t2", 2000)])
    db_session.flush()
    max_id = db_session.execute(text("SELECT MAX(id) FROM game_events")).scalar_one()
    meta = db_session.get(ProjectionMeta, "txn_ledger")
    assert meta.last_event_id == max_id

    rebuild_projection(db_session, "txn_ledger")
    db_session.flush()
    meta = db_session.get(ProjectionMeta, "txn_ledger")
    assert meta.last_event_id == max_id
    assert meta.status == "live"  # round-tripped rebuilding -> live


def test_live_and_rebuilt_watermarks_agree_for_untouched_projections(db_session):
    """A batch that touches only ONE projection must still advance EVERY
    projection's watermark to the batch max — otherwise live and rebuilt
    watermarks diverge (rebuild advances all projections to the global max).

    Regression for the live-fold/rebuild watermark divergence: previously
    record_events bumped only the projections a batch touched, so after a
    txn_ledger batch then a player_state batch, sync_state stayed behind live
    but caught up on rebuild.
    """
    folds_mod.register_builtin_folds()
    # Batch 1 (TxnPosted) touches sync_state + txn_ledger. Batch 2 (MonthSealed)
    # touches NEITHER — so after it, the still-live sync_state/txn_ledger
    # watermarks must advance to the new global max too, matching rebuild.
    record_events(db_session, [_posted(1, "t1", 1000)])
    db_session.flush()
    record_events(db_session, [GameEventDraft(
        stream="month:2026-06", type="MonthSealed", payload={})])
    db_session.flush()

    live = {m.name: m.last_event_id for m in db_session.query(ProjectionMeta).all()}
    rebuild_all(db_session)
    db_session.flush()
    rebuilt = {m.name: m.last_event_id for m in db_session.query(ProjectionMeta).all()}

    assert live == rebuilt, f"live {live} != rebuilt {rebuilt}"
    # Every registered projection sits at the global max event id, not behind it.
    max_id = db_session.execute(text("SELECT MAX(id) FROM game_events")).scalar_one()
    assert live and all(v == max_id for v in live.values()), live


def test_fold_that_raises_does_not_lose_the_event(db_session):
    folds_mod.register_fold(
        "boom", "MonthSealed",
        lambda s, p, m: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    [ev] = record_events(db_session, [GameEventDraft(stream="month:2026-06", type="MonthSealed", payload={})])
    db_session.flush()
    # Event row committed despite the fold raising.
    assert db_session.get(GameEvent, ev.id) is not None
    folds_mod._FOLDS.pop("MonthSealed", None)


# ── 17-20: integrity & migrations ────────────────────────────────────────


def test_finance_fingerprint_unchanged_across_game_activity(db_session):
    user = User(username="u", full_name="U", email="u@x.com", hashed_password="h")
    db_session.add(user)
    db_session.flush()
    acct = Account(name="Checking", type="depository", balance=10000, user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    db_session.add(Expense(title="Coffee", amount=500, date="2026-06-01",
                           category="Food", account_id=acct.id))
    db_session.flush()

    before = finance_tables_fingerprint(db_session)
    for i in range(50):
        record_events(db_session, [_posted(acct.id, f"g{i}", 100)])
    db_session.flush()
    rebuild_all(db_session)
    db_session.flush()
    after = finance_tables_fingerprint(db_session)
    assert before == after


def test_backfill_emits_one_snapshot_per_stream_and_is_idempotent(db_session):
    from server.src.services.game.backfill import run_backfill

    run_backfill(db_session)
    db_session.flush()
    count1 = db_session.execute(
        text("SELECT COUNT(*) FROM game_events WHERE type='BackfillSnapshot'")
    ).scalar_one()
    assert count1 == 2  # one per stream: player, sync
    run_backfill(db_session)
    db_session.flush()
    count2 = db_session.execute(
        text("SELECT COUNT(*) FROM game_events WHERE type='BackfillSnapshot'")
    ).scalar_one()
    assert count2 == 2  # idempotent — no duplicates


def test_game_events_table_only_inserted_from_events_module():
    """Grep guard: a ``GameEvent`` row is *constructed* only in events.py (the
    single write path).

    The ORM class is **defined** in db/models.py — that's allowed; the guard is
    about who instantiates/inserts a row. So we flag ``GameEvent(`` construction
    and raw ``INSERT INTO game_events`` anywhere except events.py and the model
    definition module.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    allowed = {"events.py", "models.py"}  # write path + class definition
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in allowed:
            continue
        text_ = path.read_text()
        if "INSERT INTO game_events" in text_ or "GameEvent(" in text_:
            offenders.append(str(path))
    assert offenders == [], f"game_events written outside events.py: {offenders}"
