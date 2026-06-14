"""Voice-input (speech-to-text) tests.

All Groq Whisper calls are mocked (per the notes). Covers: a happy-path
transcription, file-type/size/empty validation, auth, and the real Groq wiring
with the SDK mocked. Mirrors ``test_receipts.py`` — STT shares the receipt
upload pattern (auth + content-type + size, in-memory only).
"""

from server.src.services import speech_service


def _auth_header(client, username="stuser", email="st@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "ST User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _fake_transcribe(result):
    def _fn(audio_bytes, content_type):
        assert audio_bytes  # the uploaded bytes are passed through
        return result

    return _fn


def test_transcribe_returns_text(client, monkeypatch):
    headers = _auth_header(client)
    monkeypatch.setattr(
        speech_service,
        "_default_transcribe_fn",
        _fake_transcribe("  how much did I spend on gas  "),
    )
    resp = client.post(
        "/api/assistant/transcribe/",
        files={"file": ("speech.webm", b"fake-audio-bytes", "audio/webm")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # The service trims surrounding whitespace.
    assert resp.json() == {"text": "how much did I spend on gas"}


def test_transcribe_accepts_codec_param_in_content_type(client, monkeypatch):
    """Browsers send e.g. 'audio/webm;codecs=opus' — the base type must validate."""
    headers = _auth_header(client)
    monkeypatch.setattr(
        speech_service, "_default_transcribe_fn", _fake_transcribe("hello")
    )
    resp = client.post(
        "/api/assistant/transcribe/",
        files={"file": ("s.webm", b"bytes", "audio/webm;codecs=opus")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "hello"


def test_transcribe_rejects_unsupported_type(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/assistant/transcribe/",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


def test_transcribe_rejects_empty_file(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/assistant/transcribe/",
        files={"file": ("s.webm", b"", "audio/webm")},
        headers=headers,
    )
    assert resp.status_code == 400


def test_transcribe_rejects_too_large(client, monkeypatch):
    headers = _auth_header(client)
    import server.src.routers.assistant as assistant_router

    # Shrink the limit so we don't upload megabytes in a test.
    monkeypatch.setattr(assistant_router, "MAX_AUDIO_BYTES", 10)
    resp = client.post(
        "/api/assistant/transcribe/",
        files={"file": ("s.webm", b"this-is-more-than-ten-bytes", "audio/webm")},
        headers=headers,
    )
    assert resp.status_code == 413


def test_transcribe_requires_auth(client):
    resp = client.post(
        "/api/assistant/transcribe/",
        files={"file": ("s.webm", b"bytes", "audio/webm")},
    )
    assert resp.status_code == 401


def test_transcribe_failure_is_graceful(client, monkeypatch):
    """An STT/network error becomes a clean 502, never a leaked 500."""
    headers = _auth_header(client)

    def _boom(audio_bytes, content_type):
        raise RuntimeError("groq exploded")

    monkeypatch.setattr(speech_service, "_default_transcribe_fn", _boom)
    resp = client.post(
        "/api/assistant/transcribe/",
        files={"file": ("s.webm", b"bytes", "audio/webm")},
        headers=headers,
    )
    assert resp.status_code == 502


def test_default_transcribe_fn_builds_groq_request(monkeypatch):
    """Smoke test the real Groq wiring with the SDK mocked: it must use the
    configured STT model, send the bytes as a named file, and request text."""
    from types import SimpleNamespace
    from server.src.settings import settings

    captured = {}

    class _FakeGroq:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.audio = SimpleNamespace(
                transcriptions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured.update(kwargs)
            return "the transcribed text"

    monkeypatch.setattr("groq.Groq", _FakeGroq)
    monkeypatch.setattr(settings, "groq_stt_model", "whisper-test-model")

    result = speech_service._default_transcribe_fn(b"audio-bytes", "audio/webm")

    assert result == "the transcribed text"
    assert captured["model"] == "whisper-test-model"
    assert captured["response_format"] == "text"
    filename, payload = captured["file"]
    assert filename.endswith(".webm")  # extension drives codec inference
    assert payload == b"audio-bytes"


def test_speech_service_trims_and_tolerates_object_response(monkeypatch):
    """A JSON-style response object (``.text``) is handled like a bare string."""
    from types import SimpleNamespace

    svc = speech_service.SpeechService(
        transcribe_fn=lambda b, ct: "  spaced  "
    )
    assert svc.transcribe(b"x", "audio/webm") == "spaced"

    # And the default fn unwraps an object that carries ``.text``.
    class _FakeGroq:
        def __init__(self, api_key=None):
            self.audio = SimpleNamespace(
                transcriptions=SimpleNamespace(
                    create=lambda **k: SimpleNamespace(text="obj text")
                )
            )

    monkeypatch.setattr("groq.Groq", _FakeGroq)
    assert speech_service._default_transcribe_fn(b"x", "audio/mp4") == "obj text"
