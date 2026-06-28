import { useCallback, useEffect, useRef, useState } from "react";
import {
  PREFERRED_AUDIO_TYPES,
  isVoiceInputSupported,
  transcribeAudio,
} from "@/lib/voice";

/**
 * Record a short mic clip and transcribe it to text.
 *
 * Press-to-record, release-to-transcribe: `start()` opens the mic and records;
 * `stop()` finishes the clip, uploads it, and resolves with the transcript (or
 * `null` on error / empty). The component drops that text into the chat box for
 * the user to review — nothing is auto-sent. Uses only native browser APIs
 * (getUserMedia + MediaRecorder); no extra dependency. `stream` is exposed while
 * recording so a live waveform can read its amplitude.
 */
export interface VoiceInput {
  supported: boolean;
  isRecording: boolean;
  isTranscribing: boolean;
  error: string | null;
  /** The live mic stream while recording (null otherwise) — for the waveform. */
  stream: MediaStream | null;
  start: () => Promise<void>;
  stop: () => Promise<string | null>;
  cancel: () => void;
}

function pickMimeType(): string | undefined {
  // `MediaRecorder.isTypeSupported` is the only reliable cross-browser check.
  for (const type of PREFERRED_AUDIO_TYPES) {
    if (window.MediaRecorder?.isTypeSupported?.(type)) return type;
  }
  return undefined; // let the browser choose its default container.
}

export function useVoiceInput(): VoiceInput {
  const [supported] = useState(isVoiceInputSupported);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  // Release the mic (stops the browser's "recording" indicator) and clear refs.
  // Track-stopping only — the `stream` STATE is cleared by the callers so we
  // never setState from the unmount path below.
  const teardown = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  // Stop the mic if the component unmounts mid-recording.
  useEffect(() => teardown, [teardown]);

  const start = useCallback(async () => {
    if (!supported || isRecording) return;
    setError(null);
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = mediaStream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(
        mediaStream,
        mimeType ? { mimeType } : undefined
      );
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
      setStream(mediaStream);
    } catch {
      // Most often a denied mic permission; the user can still type.
      setError("Microphone unavailable. Check permissions or type instead.");
      teardown();
      setStream(null);
    }
  }, [supported, isRecording, teardown]);

  const stop = useCallback(async (): Promise<string | null> => {
    const recorder = recorderRef.current;
    if (!recorder || !isRecording) return null;

    // Wait for the recorder to flush its final chunk before assembling the blob.
    const stopped = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
    });
    recorder.stop();
    setIsRecording(false);
    await stopped;

    const type = recorder.mimeType || chunksRef.current[0]?.type || "audio/webm";
    const blob = new Blob(chunksRef.current, { type });
    teardown();
    setStream(null);

    if (blob.size === 0) return null;

    setIsTranscribing(true);
    try {
      const text = await transcribeAudio(blob);
      return text || null;
    } catch {
      setError("Could not transcribe the audio. Please type your message.");
      return null;
    } finally {
      setIsTranscribing(false);
    }
  }, [isRecording, teardown]);

  // Abandon a recording without transcribing (e.g. user taps away).
  const cancel = useCallback(() => {
    if (recorderRef.current && isRecording) {
      recorderRef.current.onstop = null;
      try {
        recorderRef.current.stop();
      } catch {
        /* already stopped */
      }
    }
    setIsRecording(false);
    teardown();
    setStream(null);
  }, [isRecording, teardown]);

  return {
    supported,
    isRecording,
    isTranscribing,
    error,
    stream,
    start,
    stop,
    cancel,
  };
}
