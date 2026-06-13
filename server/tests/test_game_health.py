"""Step 09 — fold-failure visibility & recovery.

A fold that raises must NOT hold the watermark back (the determinism contract
requires every projection to advance to the batch max, live and on rebuild).
Instead it records a per-projection ``_health`` marker so the desync is
detectable and recoverable via a rebuild — proven here.
"""

from __future__ import annotations

from server.src.db.models import ProjectionMeta
from server.src.services.game import folds as folds_mod
from server.src.services.game.events import (
    GameEventDraft,
    record_events,
    register_event_type,
)
from server.src.services.game.rebuild import rebuild_projection


_BOOM_PROJECTION = "boom_state"
_BOOM_TYPE = "BoomEvent"
_registered = False


def _boom_fold(session, payload, meta):  # noqa: ANN001 — fold signature
    raise RuntimeError("intentional fold failure")


def _register_boom():
    """Register a fold that always raises, on a fresh event type. Idempotent.

    Classify the fixture type as XP_FORBIDDEN (it's a diagnostic, never an
    action) so the global ``test_every_registered_event_type_is_classified``
    walk stays green even though we appended a type to the shared registry —
    the same hygiene the substrate applies to its own fixture types."""
    global _registered
    register_event_type(_BOOM_TYPE, 1)
    from server.src.services.game.xp import XP_FORBIDDEN

    XP_FORBIDDEN.add(_BOOM_TYPE)
    if not _registered:
        folds_mod.register_fold(_BOOM_PROJECTION, _BOOM_TYPE, _boom_fold)
        _registered = True


def test_failed_fold_marks_projection_behind(db_session):
    _register_boom()

    # Record an event whose fold raises. The finance path (record_events) must
    # NOT raise — best-effort isolation holds.
    events = record_events(db_session, [GameEventDraft(
        stream="boom", type=_BOOM_TYPE, payload={"x": 1},
        idempotency_key="boom:1",
    )])
    event_id = events[0].id

    # 1) The projection is flagged BEHIND (a _health marker exists).
    markers = folds_mod.health_markers(db_session)
    boom = [m for m in markers if m["projection"] == _BOOM_PROJECTION]
    assert boom, "expected a fold-failure marker for the failed projection"
    assert boom[0]["behind_since_event"] == event_id
    assert boom[0]["count"] >= 1

    # 2) The watermark STILL advanced to the batch max (determinism contract not
    #    regressed) — every registered projection, including the failing one.
    #    (Flush so the pending ProjectionMeta add is queryable via get.)
    db_session.flush()
    meta = db_session.get(ProjectionMeta, _BOOM_PROJECTION)
    assert meta is not None
    assert meta.last_event_id == event_id

    # 3) A successful rebuild clears the marker. (The boom fold still raises in
    #    rebuild, but rebuild swallows it and re-derives state; the marker is a
    #    live-fold signal and clears on the clean rebuild pass.)
    rebuild_projection(db_session, _BOOM_PROJECTION)
    after = folds_mod.health_markers(db_session)
    assert not [m for m in after if m["projection"] == _BOOM_PROJECTION]


def test_health_markers_empty_when_all_folds_succeed(db_session):
    folds_mod.register_builtin_folds()
    record_events(db_session, [GameEventDraft(
        stream="sync", type="TxnPosted",
        payload={"plaid_transaction_id": "t1", "account_id": 1,
                 "amount_cents": 100, "date": "2026-06-01"},
        idempotency_key="ok:1",
    )])
    # No failing fold ran → no markers.
    assert folds_mod.health_markers(db_session) == []


def _auth_header(client, username="healthuser", email="health@x.com"):
    resp = client.post("/api/signup/", json={
        "username": username, "email": email, "full_name": "Health U",
        "password": "Test-password1",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_game_health_endpoint_reports_healthy(client):
    h = _auth_header(client, "h_ok", "h_ok@x.com")
    resp = client.get("/api/game/health/", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["healthy"] is True
    assert body["behind"] == []


def test_game_health_rebuild_endpoint(client):
    h = _auth_header(client, "h_rb", "h_rb@x.com")
    # Rebuild all registered projections — returns a watermark map and clears
    # any markers. (No failure injected here; this proves the recovery trigger
    # is wired and reuses rebuild.py.)
    resp = client.post("/api/game/health/rebuild/", json={}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "rebuilt" in body
    assert isinstance(body["rebuilt"], dict)
    # An unknown projection is a 404.
    bad = client.post(
        "/api/game/health/rebuild/", json={"projection": "nope"}, headers=h
    )
    assert bad.status_code == 404
