import api from "./api";

/**
 * Client-side voice-clip guards + upload. These mirror the server limits in
 * `speech_service.py` so the user gets instant feedback, but the backend remains
 * the source of truth (it re-validates type and size).
 */
export const MAX_AUDIO_BYTES = 25 * 1024 * 1024; // 25 MB — matches the server.

/**
 * MIME types we'll try to record in, best-first. `MediaRecorder` support varies:
 * Chrome/Firefox do webm/opus; Safari does mp4. We pick the first the browser
 * supports at record time (see `useVoiceInput`); the server accepts all of these.
 */
export const PREFERRED_AUDIO_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg",
] as const;

/**
 * True when the browser can capture the mic and record it. Used to hide the mic
 * button entirely on unsupported browsers rather than offer a dead control.
 */
export function isVoiceInputSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window !== "undefined" &&
    typeof window.MediaRecorder !== "undefined"
  );
}

/**
 * POST a recorded audio Blob to the transcription endpoint and return the text.
 * Uses the shared axios instance, so the 401 → /refresh/ retry is handled for
 * us (same flow as `scanReceipt`). The caller surfaces any server `detail`.
 */
export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  // The server reads the `file` field and infers the codec from the type; give
  // the part a filename so the multipart body is well-formed.
  form.append("file", blob, "speech");
  const { data } = await api.post("/assistant/transcribe", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return ((data as { text?: string })?.text ?? "").trim();
}
