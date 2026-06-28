import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/apiBase";

/**
 * Spoken replies (P7, server flag default-OFF). The Clerk reads a reply the user
 * ALREADY has as text — never audio-only. Capability is probed once per session
 * with a zero-cost empty-text request (400 = enabled, 404 = off); the toggle is
 * only shown when available. Playback is gated behind the user's toggle gesture,
 * satisfying autoplay policy.
 */
const SPEAK_URL = `${apiBase}/assistant/speak/`;
const ENABLED_KEY = "clerk:tts-enabled";

let ttsUnavailable = false;
let probed = false;

async function probeTts(): Promise<boolean> {
  if (probed) return !ttsUnavailable;
  probed = true;
  try {
    const res = await fetch(SPEAK_URL, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "" }),
    });
    // 404 = flag off. Anything else (400 for empty text) = available, no Groq
    // call and no budget spent.
    if (res.status === 404) {
      ttsUnavailable = true;
      return false;
    }
    return true;
  } catch {
    ttsUnavailable = true;
    return false;
  }
}

export interface ClerkTts {
  available: boolean;
  enabled: boolean;
  speaking: boolean;
  toggle: () => void;
  speak: (text: string) => Promise<void>;
  stop: () => void;
}

export function useClerkTts(): ClerkTts {
  const [available, setAvailable] = useState(false);
  const [enabled, setEnabled] = useState(() => {
    try {
      return localStorage.getItem(ENABLED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let alive = true;
    void probeTts().then((ok) => {
      if (alive) setAvailable(ok);
    });
    return () => {
      alive = false;
    };
  }, []);

  const cleanupAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    cleanupAudio();
    setSpeaking(false);
  }, [cleanupAudio]);

  // Stop + free the audio on unmount.
  useEffect(() => () => cleanupAudio(), [cleanupAudio]);

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(ENABLED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      if (!next) stop();
      return next;
    });
  }, [stop]);

  const speak = useCallback(
    async (text: string) => {
      const clean = (text || "").trim();
      if (!clean || ttsUnavailable) return;
      try {
        const res = await fetch(SPEAK_URL, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: clean }),
        });
        if (res.status === 404) {
          ttsUnavailable = true;
          setAvailable(false);
          return;
        }
        if (!res.ok) return;
        const blob = await res.blob();
        cleanupAudio();
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = () => setSpeaking(false);
        audio.onerror = () => setSpeaking(false);
        setSpeaking(true);
        await audio.play().catch(() => setSpeaking(false));
      } catch {
        setSpeaking(false);
      }
    },
    [cleanupAudio]
  );

  return { available, enabled, speaking, toggle, speak, stop };
}
