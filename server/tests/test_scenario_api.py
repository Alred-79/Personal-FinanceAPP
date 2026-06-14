"""Scenario CRUD API tests (v6 doc 03).

Covers the happy-path CRUD, ownership isolation (another user's id → 404), the
dollar→cents conversion that happens on create (asserted against the raw stored
``overlay_json``), and the dollar round-trip on get.
"""

import json

from server.src.db.models import Scenario as ScenarioORM


def _auth_header(client, username="suser", email="s@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Scenario User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _overlay_payload():
    """A fully-populated dollar overlay exercising every money field."""
    return {
        "added_recurring": [
            {
                "title": "Gym",
                "amount": 49.99,
                "recurrence": "monthly",
                "kind": "expense",
                "category": "Health",
            }
        ],
        "excluded_source_ids": [["expense", 7]],
        "overridden_recurring": [
            {"source_id": 3, "kind": "income", "amount": 2500.00}
        ],
        "discrete_flows": [
            {"date": "2026-08-01", "amount": 1200.00, "kind": "expense", "title": "Roof"}
        ],
        "goal_mutations": [
            {"goal_id": 5, "amount": 10000.00, "progress": 250.50}
        ],
        "balance_override": 3333.33,
        "config_overrides": {"s2s_buffer_on": True},
    }


class TestScenarioCRUD:
    def test_create_list_get_update_delete(self, client):
        headers = _auth_header(client)

        # Create
        resp = client.post(
            "/api/scenarios/",
            json={"name": "Aggressive Save", "overlay": _overlay_payload()},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        created = resp.json()
        sid = created["id"]
        assert created["name"] == "Aggressive Save"
        assert created["overlay"]["added_recurring"][0]["amount"] == 49.99

        # List
        listed = client.get("/api/scenarios/", headers=headers).json()
        assert len(listed) == 1
        assert listed[0]["id"] == sid

        # Get
        got = client.get(f"/api/scenarios/{sid}/", headers=headers).json()
        assert got["name"] == "Aggressive Save"

        # Update
        upd = client.put(
            f"/api/scenarios/{sid}/",
            json={"name": "Renamed", "overlay": {"discrete_flows": []}},
            headers=headers,
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["name"] == "Renamed"
        assert upd.json()["overlay"]["added_recurring"] == []

        # Delete
        dele = client.delete(f"/api/scenarios/{sid}/", headers=headers)
        assert dele.status_code == 200
        assert client.get("/api/scenarios/", headers=headers).json() == []
        assert client.get(f"/api/scenarios/{sid}/", headers=headers).status_code == 404

    def test_create_with_empty_overlay(self, client):
        """Name-only create (default empty overlay) round-trips cleanly."""
        headers = _auth_header(client, "empty", "empty@t.com")
        resp = client.post(
            "/api/scenarios/", json={"name": "Blank"}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        out = resp.json()
        assert out["overlay"]["added_recurring"] == []
        assert out["overlay"]["balance_override"] is None


class TestOwnership:
    def test_other_users_scenario_is_404(self, client):
        headers_a = _auth_header(client, "a", "a@t.com")
        headers_b = _auth_header(client, "b", "b@t.com")

        sid = client.post(
            "/api/scenarios/",
            json={"name": "A's plan", "overlay": _overlay_payload()},
            headers=headers_a,
        ).json()["id"]

        # B sees none of A's scenarios.
        assert client.get("/api/scenarios/", headers=headers_b).json() == []
        # B cannot read, update, or delete A's scenario — each is a 404.
        assert client.get(f"/api/scenarios/{sid}/", headers=headers_b).status_code == 404
        assert (
            client.put(
                f"/api/scenarios/{sid}/",
                json={"name": "hijack", "overlay": {}},
                headers=headers_b,
            ).status_code
            == 404
        )
        assert (
            client.delete(f"/api/scenarios/{sid}/", headers=headers_b).status_code == 404
        )
        # A's scenario is untouched.
        assert client.get(f"/api/scenarios/{sid}/", headers=headers_a).status_code == 200


class TestCentsDiscipline:
    def test_overlay_stored_as_cents(self, client, db_session):
        """The dollar amounts on the wire must be integer cents in storage."""
        headers = _auth_header(client, "cents", "cents@t.com")
        sid = client.post(
            "/api/scenarios/",
            json={"name": "Cents", "overlay": _overlay_payload()},
            headers=headers,
        ).json()["id"]

        row = db_session.get(ScenarioORM, sid)
        stored = json.loads(row.overlay_json)
        assert stored["schema_version"] == 1
        # Every money field is whole cents — no floats survived into storage.
        assert stored["added_recurring"][0]["amount_cents"] == 4999
        assert stored["overridden_recurring"][0]["amount_cents"] == 250000
        assert stored["discrete_flows"][0]["amount_cents"] == 120000
        assert stored["goal_mutations"][0]["amount_cents"] == 1000000
        assert stored["goal_mutations"][0]["progress_cents"] == 25050
        assert stored["balance_override_cents"] == 333333
        assert isinstance(stored["added_recurring"][0]["amount_cents"], int)

    def test_dollar_round_trip_on_get(self, client):
        """create→get returns the same dollar amounts it was given."""
        headers = _auth_header(client, "rt", "rt@t.com")
        payload = _overlay_payload()
        sid = client.post(
            "/api/scenarios/",
            json={"name": "RT", "overlay": payload},
            headers=headers,
        ).json()["id"]

        got = client.get(f"/api/scenarios/{sid}/", headers=headers).json()
        ov = got["overlay"]
        assert ov["added_recurring"][0]["amount"] == 49.99
        assert ov["overridden_recurring"][0]["amount"] == 2500.00
        assert ov["discrete_flows"][0]["amount"] == 1200.00
        assert ov["goal_mutations"][0]["amount"] == 10000.00
        assert ov["goal_mutations"][0]["progress"] == 250.50
        assert ov["balance_override"] == 3333.33
        assert ov["excluded_source_ids"] == [["expense", 7]]
        assert ov["config_overrides"] == {"s2s_buffer_on": True}


def _create_account(client, headers, balance=3000.00):
    resp = client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": balance},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


# ── doc 04: evaluate + compare endpoints ─────────────────────────────────────


class TestEvaluateEndpoint:
    def test_evaluate_shape_and_auth(self, client):
        headers = _auth_header(client, "ev", "ev@t.com")
        _create_account(client, headers, balance=3000.00)
        sid = client.post(
            "/api/scenarios/",
            json={"name": "Low balance", "overlay": {"balance_override": 50.0}},
            headers=headers,
        ).json()["id"]

        resp = client.post(f"/api/scenarios/{sid}/evaluate/", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"baseline", "scenario"}
        assert body["scenario"]["scenario_id"] == sid
        for col in (body["baseline"], body["scenario"]):
            assert {
                "overdraft_probability",
                "lowest_balance",
                "ending_balance",
                "safe_to_spend",
                "runway_days",
                "goal_reach",
            } <= set(col["result"])
        # A $50 starting balance is far below the real $3,000 → ending drops.
        assert body["scenario"]["delta"]["ending_balance"] < 0.0

    def test_evaluate_requires_auth(self, client):
        assert client.post("/api/scenarios/1/evaluate/").status_code == 401

    def test_evaluate_other_users_scenario_404(self, client):
        ha = _auth_header(client, "oa", "oa@t.com")
        hb = _auth_header(client, "ob", "ob@t.com")
        sid = client.post(
            "/api/scenarios/", json={"name": "A"}, headers=ha
        ).json()["id"]
        assert (
            client.post(f"/api/scenarios/{sid}/evaluate/", headers=hb).status_code == 404
        )


class TestCompareEndpoint:
    def test_compare_columns(self, client):
        headers = _auth_header(client, "cmp", "cmp@t.com")
        _create_account(client, headers, balance=3000.00)
        s1 = client.post(
            "/api/scenarios/",
            json={"name": "Tight", "overlay": {"balance_override": 100.0}},
            headers=headers,
        ).json()["id"]
        s2 = client.post(
            "/api/scenarios/",
            json={"name": "Flush", "overlay": {"balance_override": 9000.0}},
            headers=headers,
        ).json()["id"]

        resp = client.post(
            "/api/scenarios/compare/",
            json={"scenario_ids": [s1, s2], "horizon_days": 60},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        cols = resp.json()["columns"]
        assert len(cols) == 3
        assert cols[0]["name"] == "Baseline"
        assert cols[1]["scenario_id"] == s1
        assert cols[2]["scenario_id"] == s2
        # Flush ends richer than Tight.
        assert cols[1]["delta"]["ending_balance"] < cols[2]["delta"]["ending_balance"]

    def test_compare_unknown_id_404(self, client):
        headers = _auth_header(client, "cmp2", "cmp2@t.com")
        resp = client.post(
            "/api/scenarios/compare/",
            json={"scenario_ids": [999999], "horizon_days": 30},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_compare_requires_auth(self, client):
        resp = client.post(
            "/api/scenarios/compare/", json={"scenario_ids": [1]}
        )
        assert resp.status_code == 401
