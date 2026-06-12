"""v4 package 02 — game-mode API + helper tests (groups 11-14).

PATCH (via PUT /settings/preferences/) validates the enum, persists, and emits
zero game events (a settings change is not a financial action — XP hygiene).
``should_generate_flavor`` gates server-side generation on the mode.
"""

from __future__ import annotations

from sqlalchemy import text

from server.src.models import UserInDB
from server.src.services.game.mode import should_generate_flavor


def _auth_header(client, username="modeuser", email="mode@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Mode User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


# ── 11: enum validation + persistence + round-trip ───────────────────────


def test_game_mode_defaults_to_off(client):
    h = _auth_header(client, "m_def", "m_def@x.com")
    resp = client.get("/api/settings/", headers=h)
    assert resp.status_code == 200
    assert resp.json()["preferences"]["game_mode"] == "off"


def test_patch_game_mode_persists_and_round_trips(client):
    h = _auth_header(client, "m_rt", "m_rt@x.com")
    resp = client.put(
        "/api/settings/preferences/", json={"game_mode": "full"}, headers=h
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["game_mode"] == "full"
    # GET round-trips the persisted value.
    got = client.get("/api/settings/", headers=h).json()
    assert got["preferences"]["game_mode"] == "full"


def test_patch_game_mode_rejects_invalid_enum(client):
    h = _auth_header(client, "m_bad", "m_bad@x.com")
    resp = client.put(
        "/api/settings/preferences/", json={"game_mode": "rpg"}, headers=h
    )
    assert resp.status_code == 400, resp.text
    # The mode is unchanged after a rejected update.
    got = client.get("/api/settings/", headers=h).json()
    assert got["preferences"]["game_mode"] == "off"


def test_all_three_modes_accepted(client, db_session):
    h = _auth_header(client, "m_all", "m_all@x.com")
    # Package 10: first game activation assigns the experiment cohort, and a
    # holdout user's mode is locked 'off' (the spine is never withheld; the
    # game layer is). This user happens to hash into the holdout bucket, so
    # pin the 'game' cohort first — this test is about the mode enum, and the
    # holdout lock has its own tests in test_experiments.py.
    db_session.execute(
        text("UPDATE users SET experiment_cohort = 'game' WHERE username = 'm_all'")
    )
    for mode in ("ambient", "full", "off"):
        resp = client.put(
            "/api/settings/preferences/", json={"game_mode": mode}, headers=h
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["game_mode"] == mode


# ── 12: a mode change emits zero game events (XP hygiene) ─────────────────


def test_patch_game_mode_emits_no_game_events(client, db_session):
    # db_session and the client's session share the same in-memory engine
    # (conftest binds both to _engine), so we can read game_events here.
    h = _auth_header(client, "m_ev", "m_ev@x.com")
    before = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")
    ).scalar_one()
    resp = client.put(
        "/api/settings/preferences/", json={"game_mode": "full"}, headers=h
    )
    assert resp.status_code == 200
    after = db_session.execute(
        text("SELECT COUNT(*) FROM game_events")
    ).scalar_one()
    assert after == before  # no events from a settings change


# ── 13: should_generate_flavor gate ──────────────────────────────────────


def test_should_generate_flavor_gates_on_mode():
    def _user(mode):
        return UserInDB(
            id=1,
            username="u",
            email="u@x.com",
            full_name="U",
            disabled=False,
            hashed_password="x",
            game_mode=mode,
        )

    assert should_generate_flavor(_user("off")) is False
    assert should_generate_flavor(_user("ambient")) is True
    assert should_generate_flavor(_user("full")) is True


# ── 14: finance tables untouched across a mode change ────────────────────


def test_mode_change_leaves_finance_tables_untouched(client, db_session):
    from server.tests.integrity import finance_tables_fingerprint

    h = _auth_header(client, "m_fp", "m_fp@x.com")
    before = finance_tables_fingerprint(db_session)
    client.put("/api/settings/preferences/", json={"game_mode": "full"}, headers=h)
    after = finance_tables_fingerprint(db_session)
    assert before == after
