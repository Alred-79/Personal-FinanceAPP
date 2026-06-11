"""Notification endpoint tests."""

from datetime import date


def _auth_header(client, username="nuser", email="n@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "N User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _create_account(client, headers, balance=1000.00):
    resp = client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": balance},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


def _trigger_budget_overrun(client, headers):
    """Create a $10 Food budget then spend $50 against it to trigger overrun."""
    acct_id = _create_account(client, headers)
    client.post(
        "/api/budgets/",
        json={"category": "Food", "monthly_limit": 10.0, "rollover": False},
        headers=headers,
    )
    today = date.today().replace(day=1).isoformat()
    client.post(
        "/api/expenses/",
        json={
            "title": "Huge meal",
            "amount": 50.0,
            "date": today,
            "category": "Food",
            "account_id": acct_id,
        },
        headers=headers,
    )


class TestNotificationsShape:
    def test_get_notifications_returns_shape(self, client):
        h = _auth_header(client)
        resp = client.get("/api/notifications/", headers=h)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "items" in body
        assert "unread_count" in body

    def test_fresh_user_has_zero_unread(self, client):
        h = _auth_header(client, "nfresh", "nfresh@x.com")
        body = client.get("/api/notifications/", headers=h).json()
        assert body["unread_count"] == 0
        assert body["items"] == []


class TestNotificationGeneration:
    def test_budget_overrun_generates_notification(self, client):
        h = _auth_header(client, "nover", "nover@x.com")
        _trigger_budget_overrun(client, h)
        resp = client.get("/api/notifications/", headers=h)
        assert resp.status_code == 200
        assert resp.json()["unread_count"] >= 1

    def test_unread_only_filter(self, client):
        h = _auth_header(client, "nfilt", "nfilt@x.com")
        _trigger_budget_overrun(client, h)
        resp = client.get("/api/notifications/?unread_only=true", headers=h)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(not item["read"] for item in items)


class TestMarkRead:
    def test_mark_single_notification_read(self, client):
        h = _auth_header(client, "nread", "nread@x.com")
        _trigger_budget_overrun(client, h)
        items = client.get("/api/notifications/", headers=h).json()["items"]
        nid = items[0]["id"]
        resp = client.put(f"/api/notifications/{nid}/read/", headers=h)
        assert resp.status_code == 200
        updated = client.get("/api/notifications/", headers=h).json()["items"]
        assert next(n for n in updated if n["id"] == nid)["read"] is True

    def test_mark_all_read_sets_unread_count_to_zero(self, client):
        h = _auth_header(client, "nall", "nall@x.com")
        _trigger_budget_overrun(client, h)
        resp = client.put("/api/notifications/read-all/", headers=h)
        assert resp.status_code == 200
        after = client.get("/api/notifications/", headers=h).json()
        assert after["unread_count"] == 0
