import { useEffect, useRef } from "react";
import { Check, X, Loader2 } from "lucide-react";
import styles from "./ClerkVoice.module.css";
import { useReducedMotion } from "@/hooks/useEnvironment";

interface ClerkVoiceProps {
  /** The live mic stream (null while transcribing). */
  stream: MediaStream | null;
  isTranscribing: boolean;
  /** Finish + transcribe; the transcript lands in the box for review. */
  onStop: () => void;
  /** Abandon the recording. */
  onCancel: () => void;
}

/** Live amplitude oscilloscope drawn from the mic stream onto a canvas. */
function Waveform({ stream }: { stream: MediaStream | null }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = ref.current;
    if (!stream || !cv) return;
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctor) return;

    const audio = new Ctor();
    let analyser: AnalyserNode | null = null;
    let src: MediaStreamAudioSourceNode | null = null;
    try {
      src = audio.createMediaStreamSource(stream);
      analyser = audio.createAnalyser();
      analyser.fftSize = 128;
      analyser.smoothingTimeConstant = 0.75;
      src.connect(analyser);
    } catch {
      audio.close().catch(() => {});
      return;
    }

    const bins = analyser.frequencyBinCount; // 64
    const data = new Uint8Array(bins);
    const color = getComputedStyle(cv).color || "#aa8f2c";
    const N = 28;
    const gap = 2;
    let raf = 0;

    const draw = () => {
      raf = requestAnimationFrame(draw);
      if (!analyser) return;
      const dpr = window.devicePixelRatio || 1;
      const w = cv.clientWidth;
      const h = cv.clientHeight;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
        cv.width = Math.round(w * dpr);
        cv.height = Math.round(h * dpr);
      }
      const c = cv.getContext("2d");
      if (!c) return;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, w, h);
      c.fillStyle = color;
      analyser.getByteFrequencyData(data);
      const bw = Math.max(1.5, (w - (N - 1) * gap) / N);
      for (let i = 0; i < N; i++) {
        const v = data[Math.floor((i / N) * bins)] / 255; // 0..1
        const bh = Math.max(2, v * v * h); // emphasise peaks, keep a baseline
        c.fillRect(i * (bw + gap), (h - bh) / 2, bw, bh);
      }
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      try {
        src?.disconnect();
        analyser?.disconnect();
      } catch {
        /* already torn down */
      }
      audio.close().catch(() => {});
    };
  }, [stream]);

  return <canvas ref={ref} className={styles.wave} aria-hidden />;
}

/**
 * The listening surface shown in place of the composer while the mic is live.
 * A live oscilloscope makes "it's hearing me" tangible; ✓ finishes and
 * transcribes (text lands in the box for review — never auto-sent), ✕ abandons.
 * Reduced motion swaps the animated wave for a static engraved row.
 */
export function ClerkVoice({ stream, isTranscribing, onStop, onCancel }: ClerkVoiceProps) {
  const reduce = useReducedMotion();
  return (
    <div className={styles.voice}>
      {!isTranscribing && (
        <button
          type="button"
          className={styles.iconBtn}
          onClick={onCancel}
          aria-label="Cancel recording"
        >
          <X className={styles.icon} />
        </button>
      )}

      <div className={styles.stage} role="status" aria-live="polite">
        {isTranscribing ? (
          <div className={styles.transcribing}>
            <Loader2 className={`${styles.icon} ${styles.spin}`} aria-hidden />
            Reading your words…
          </div>
        ) : (
          <>
            {reduce ? (
              <div className={styles.staticBars} aria-hidden>
                {Array.from({ length: 28 }).map((_, i) => (
                  <i key={i} style={{ height: `${6 + (i % 5) * 4}px` }} />
                ))}
              </div>
            ) : (
              <Waveform stream={stream} />
            )}
            <span className={styles.label}>
              <span className={styles.dot} aria-hidden />
              Listening — tap ✓ when you&rsquo;re done
            </span>
          </>
        )}
      </div>

      {!isTranscribing && (
        <button
          type="button"
          className={`${styles.iconBtn} ${styles.stop}`}
          onClick={onStop}
          aria-label="Finish and transcribe"
        >
          <Check className={styles.icon} />
        </button>
      )}
    </div>
  );
}
