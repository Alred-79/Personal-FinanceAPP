"""Tests for the Clerk's text-to-speech endpoint (P7).

Spoken replies via Groq PlayAI TTS. OFF by default (404); the synthesis call is
injected so tests never touch the SDK. The transcript is always shown elsewhere
— this endpoint only produces the optional audio.
"""

from server.src.settings import settings
from server.src.services import speech_service


def _auth_header(client, username="vuser", email="v@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "V User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


class TestSpeak:
    def test_404_when_flag_off(self, client):
        h = _auth_header(client, "tts_off", "ttsoff@x.com")
        resp = client.post("/api/assistant/speak/", json={"text": "hello"}, headers=h)
        assert resp.status_code == 404

    def test_requires_auth(self, client):
        resp = client.post("/api/assistant/speak/", json={"text": "hello"})
        assert resp.status_code in (401, 403)

    def test_synthesizes_wav(self, client, monkeypatch):
        monkeypatch.setattr(settings, "assistant_tts_enabled", True)
        monkeypatch.setattr(
            speech_service, "_default_synthesize_fn", lambda text: b"FAKEWAVDATA"
        )
        h = _auth_header(client, "tts_on", "ttson@x.com")
        resp = client.post(
            "/api/assistant/speak/", json={"text": "You spent $40."}, headers=h
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("audio/wav")
        assert resp.content == b"FAKEWAVDATA"

    def test_empty_text_is_400_when_enabled(self, client, monkeypatch):
        """The client probes with empty text: 400 means "enabled" (no Groq call,
        no budget spent), 404 means "off". This asserts the 400 branch."""
        monkeypatch.setattr(settings, "assistant_tts_enabled", True)
        h = _auth_header(client, "tts_probe", "ttsprobe@x.com")
        resp = client.post("/api/assistant/speak/", json={"text": "   "}, headers=h)
        assert resp.status_code == 400

    def test_synth_failure_is_502(self, client, monkeypatch):
        monkeypatch.setattr(settings, "assistant_tts_enabled", True)

        def boom(text):
            raise RuntimeError("groq down")

        monkeypatch.setattr(speech_service, "_default_synthesize_fn", boom)
        h = _auth_header(client, "tts_fail", "ttsfail@x.com")
        resp = client.post("/api/assistant/speak/", json={"text": "hello"}, headers=h)
        assert resp.status_code == 502
