import { useState } from "react";
import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * A struck commemorative coin for the Cabinet — minted when a goal is met. Gold
 * medallion, a two-line engraved face, a 3-D tilt toward the cursor, and a
 * strike animation (on mount + re-strike on click). Gold is the game-layer
 * accent here, never a money figure. Reduced-motion renders it still.
 */
const STRIKE = [0.34, 1.4, 0.64, 1] as const;

export function MintedCoin({ label, size = 84 }: { label: string; size?: number }) {
  const reduce = useReducedMotion();
  const [n, setN] = useState(0); // bump to replay the strike
  // Two short lines from the label so it reads like a struck legend.
  const words = label.toUpperCase().split(/\s+/);
  const mid = Math.ceil(words.length / 2);
  const lines = words.length > 1 ? [words.slice(0, mid).join(" "), words.slice(mid).join(" ")] : words;

  const [tilt, setTilt] = useState({ rx: 0, ry: 0 });

  return (
    <motion.button
      type="button"
      onClick={() => setN((x) => x + 1)}
      aria-label={`${label} — minted`}
      className="relative grid shrink-0 place-items-center rounded-full focus-visible:outline-none"
      style={{
        width: size,
        height: size,
        background: "radial-gradient(circle at 38% 32%, hsl(var(--gold)), hsl(var(--gold) / 0.5))",
        boxShadow: "0 8px 22px hsl(222 40% 4% / 0.4), inset 0 0 0 3px hsl(var(--paper-high) / 0.3)",
        transformStyle: "preserve-3d",
        transformPerspective: 600,
      }}
      initial={reduce ? false : { scale: 2, rotateY: 180, opacity: 0 }}
      animate={reduce ? {} : { scale: 1, rotateY: tilt.ry, rotateX: tilt.rx, opacity: 1 }}
      transition={{ duration: 0.6, ease: STRIKE }}
      key={n}
      onPointerMove={(e) => {
        if (reduce) return;
        const r = e.currentTarget.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width;
        const py = (e.clientY - r.top) / r.height;
        setTilt({ rx: (0.5 - py) * 24, ry: (px - 0.5) * 28 });
      }}
      onPointerLeave={() => setTilt({ rx: 0, ry: 0 })}
    >
      <span
        className="font-display text-[0.58rem] font-semibold leading-[1.05] text-[hsl(222_45%_11%)]"
        style={{ transform: "translateZ(8px)" }}
      >
        {lines.map((l, i) => (
          <span key={i} className="block">
            {l}
          </span>
        ))}
      </span>
    </motion.button>
  );
}
