"""Receipt scanning tests.

All Groq vision calls are mocked (per the notes). Covers: a sample
receipt yielding a correct prefilled draft, file-type/size validation, the
category fallback, and auth.
"""

from server.src.services import receipt_service


def _auth_header(client, username="rcuser", email="rc@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "RC User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _fake_vision(result):
    def _fn(image_b64, content_type):
        assert image_b64  # base64 of the uploaded bytes is passed through
        return result

    return _fn


def test_scan_returns_prefilled_draft(client, monkeypatch):
    headers = _auth_header(client)
    monkeypatch.setattr(
        receipt_service,
        "_default_vision_fn",
        _fake_vision(
            {
                "merchant": "Target",
                "total": 42.17,
                "date": "2026-05-03",
                "category": "Shops",
                "line_items": [
                    {"description": "Towels", "amount": 20.0},
                    {"description": "Soap", "amount": 22.17},
                ],
            }
        ),
    )

    resp = client.post(
        "/api/receipts/scan/",
        files={"file": ("receipt.png", b"\x89PNG fake bytes", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    draft = resp.json()
    assert draft["merchant"] == "Target"
    assert draft["title"] == "Target"
    assert draft["amount"] == 42.17
    assert draft["date"] == "2026-05-03"
    assert draft["category"] == "Shops"
    assert len(draft["line_items"]) == 2


def test_scan_parses_messy_total_and_date(client, monkeypatch):
    headers = _auth_header(client)
    monkeypatch.setattr(
        receipt_service,
        "_default_vision_fn",
        _fake_vision(
            {
                "merchant": "Cafe",
                "total": "$12.50",
                "date": "05/03/2026",
                "category": None,
                "line_items": [],
            }
        ),
    )
    resp = client.post(
        "/api/receipts/scan/",
        files={"file": ("r.jpg", b"jpeg-bytes", "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    draft = resp.json()
    assert draft["amount"] == 12.50
    assert draft["date"] == "2026-05-03"


def test_scan_category_fallback(client, monkeypatch):
    """When the model omits the category, the categorizer fills it in."""
    headers = _auth_header(client)
    monkeypatch.setattr(
        receipt_service,
        "_default_vision_fn",
        _fake_vision(
            {
                "merchant": "Starbucks Store 123",
                "total": 5.75,
                "date": "2026-05-01",
                "category": None,
                "line_items": [],
            }
        ),
    )
    resp = client.post(
        "/api/receipts/scan/",
        files={"file": ("r.png", b"png-bytes", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # "starbucks" keyword rule → Food and Drink.
    assert resp.json()["category"] == "Food and Drink"


def test_scan_rejects_unsupported_type(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/receipts/scan/",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


def test_scan_rejects_empty_file(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/receipts/scan/",
        files={"file": ("r.png", b"", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 400


def test_scan_rejects_too_large(client, monkeypatch):
    headers = _auth_header(client)
    # Shrink the limit so we don't have to upload megabytes in a test.
    import server.src.routers.receipts as receipts_router

    monkeypatch.setattr(receipts_router, "MAX_IMAGE_BYTES", 10)
    resp = client.post(
        "/api/receipts/scan/",
        files={"file": ("r.png", b"this-is-more-than-ten-bytes", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 413


def test_scan_requires_auth(client):
    resp = client.post(
        "/api/receipts/scan/",
        files={"file": ("r.png", b"png-bytes", "image/png")},
    )
    assert resp.status_code == 401


def test_default_vision_fn_builds_groq_request(monkeypatch):
    """Smoke test the real Groq wiring with the SDK mocked: it must use the
    configured model, JSON mode, and pass the image as a base64 data URL."""
    import json
    from types import SimpleNamespace
    from server.src.settings import settings

    captured = {}

    class _FakeGroq:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured.update(kwargs)
            content = json.dumps(
                {
                    "merchant": "Deli",
                    "total": "9.99",
                    "date": "2026-05-02",
                    "category": "Food and Drink",
                    "line_items": [],
                }
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=content))
                ]
            )

    monkeypatch.setattr("groq.Groq", _FakeGroq)
    monkeypatch.setattr(settings, "groq_vision_model", "vision-test-model")

    result = receipt_service._default_vision_fn("QkFTRTY0", "image/png")

    assert result["merchant"] == "Deli"
    assert captured["model"] == "vision-test-model"
    assert captured["response_format"] == {"type": "json_object"}
    content = captured["messages"][0]["content"]
    image_parts = [p for p in content if p.get("type") == "image_url"]
    assert image_parts[0]["image_url"]["url"] == "data:image/png;base64,QkFTRTY0"
    assert any(p.get("type") == "text" for p in content)
