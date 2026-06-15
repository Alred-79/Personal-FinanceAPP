import { useStore } from "@/store/store";

/**
 * MoodWatermark — a faint, large engraved figure behind the page that reflects
 * the user's financial state: a rising sun when the forecast stays solvent, a
 * gathering storm when it dips negative. Atmosphere, never information: it sits
 * at z-0 behind everything at very low opacity and is aria-hidden, so it never
 * competes with or decorates a money figure (color law intact).
 *
 * Present in every mode (it's finance-derived, not game chrome). Time-of-day ink
 * warming is reserved for full mode (flags.moodTimeOfDay) and added later.
 *
 * Reads the already-loaded forecast from the store — no extra fetch.
 */
export function MoodWatermark() {
  const forecast = useStore((s) => s.forecast);

  // Until a forecast exists, render nothing (no guess about mood).
  if (!forecast) return null;
  const stormy = forecast.will_go_negative === true;

  return (
    <div
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        display: "grid",
        placeItems: "center",
        opacity: 0.05,
      }}
    >
      <svg
        viewBox="0 0 200 120"
        style={{ width: "min(70vw, 640px)", height: "auto", color: "hsl(var(--rule-strong))" }}
      >
        {stormy ? (
          // gathering storm: a cloud with falling rule-lines
          <g stroke="currentColor" strokeWidth={1.2} fill="none">
            <path d="M50 70 q-14 0 -14 -14 q0 -14 16 -13 q4 -16 22 -12 q10 -12 26 -2 q18 -6 22 12 q14 1 12 15 q-2 12 -16 11 Z" />
            <line x1="70" y1="86" x2="62" y2="104" />
            <line x1="96" y1="86" x2="88" y2="104" />
            <line x1="122" y1="86" x2="114" y2="104" />
          </g>
        ) : (
          // rising sun over a horizon
          <g stroke="currentColor" strokeWidth={1.2} fill="none">
            <circle cx="100" cy="95" r="26" />
            {Array.from({ length: 11 }, (_, i) => {
              const a = ((200 + i * 14) * Math.PI) / 180;
              return (
                <line
                  key={i}
                  x1={(100 + 30 * Math.cos(a)).toFixed(0)}
                  y1={(95 + 30 * Math.sin(a)).toFixed(0)}
                  x2={(100 + 44 * Math.cos(a)).toFixed(0)}
                  y2={(95 + 44 * Math.sin(a)).toFixed(0)}
                />
              );
            })}
            <line x1="20" y1="95" x2="180" y2="95" />
          </g>
        )}
      </svg>
    </div>
  );
}
