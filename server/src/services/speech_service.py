"""Speech-to-text via Groq Whisper.

Upload a short audio clip from the in-app mic → Groq Whisper → a plain-text
transcript that pre-fills the assistant's input box for the user to review before
sending. No new vendor or key: Groq (already the app's LLM provider) hosts
Whisper, so this reuses ``settings.groq_api_key``.

PII NOTE
--------
Spoken audio can hold sensitive PII (an account number read aloud, a phone
number). Like a receipt image, the bytes live only in memory for the length of
the request and are dropped once the transcript is pulled out — nothing touches
disk or the database. The transcript itself is returned to the *user's own
browser* for review; it is the chat path (see ``assistant_service`` /
``pii.scrub_secrets``) that scrubs high-risk tokens before any text reaches Groq
for inference, so a spoken SSN is redacted exactly like a typed one.

The Groq call is injected as ``transcribe_fn`` so it is trivially mockable in
tests (Mock all Groq calls in tests), mirroring ``ReceiptService``.
"""

from __future__ import annotations

from typing import Callable, Optional

# (audio_bytes, content_type) -> raw transcript string from the STT model.
TranscribeFn = Callable[[bytes, str], str]

# Upload validation limits. ``MediaRecorder`` emits audio/webm on Chrome/Firefox
# and audio/mp4 on Safari; accept the common container/codec types either browser
# produces, plus the lossless ones a desktop client might send.
ALLOWED_CONTENT_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
}
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB — Groq's per-file limit (~25 min Opus).

# Map an accepted content type to a filename extension. Groq infers the codec
# from the filename, so a wrong/blank extension makes it reject otherwise-valid
# audio. Defaults to a safe container if an odd-but-allowed type slips through.
_EXT_FOR_TYPE = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
}


def _default_transcribe_fn(audio_bytes: bytes, content_type: str) -> str:
    """Call Groq's Whisper transcription. Imported lazily so tests skip the SDK."""
    from groq import Groq

    from ..settings import settings

    ext = _EXT_FOR_TYPE.get(content_type, "webm")
    client = Groq(api_key=settings.groq_api_key)
    transcript = client.audio.transcriptions.create(
        # Groq's SDK takes a (filename, bytes) tuple; the extension tells it the
        # codec. ``response_format="text"`` returns a bare string, not JSON.
        file=(f"audio.{ext}", audio_bytes),
        model=settings.groq_stt_model,
        response_format="text",
    )
    # The text format yields a plain str; older/JSON paths yield an object with a
    # ``.text`` attribute. Handle both so a format change can't 500 us.
    if isinstance(transcript, str):
        return transcript
    return getattr(transcript, "text", "") or ""


class SpeechService:
    """Transcribes a short audio clip to text."""

    def __init__(self, transcribe_fn: Optional[TranscribeFn] = None) -> None:
        self.transcribe_fn = transcribe_fn or _default_transcribe_fn

    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        """Return the trimmed transcript. May raise from ``transcribe_fn``."""
        text = self.transcribe_fn(audio_bytes, content_type) or ""
        return text.strip()
