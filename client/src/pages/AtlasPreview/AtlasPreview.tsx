/**
 * THROWAWAY dev preview (frontend-elevation) — the POWERFUL version. Real WebGL
 * guilloché (OGL) + Motion-driven cards (spring 3D tilt, staggered entrance) +
 * count-up hero + burin cursor. Outside the auth wall for screenshotting. Remove
 * after review.
 */
import { useEffect, useRef, useState } from "react";
import { motion, animate } from "motion/react";
import { GuillocheGL } from "@/components/atlas/GuillocheGL";
import { BurinCursor } from "@/components/atlas/BurinCursor";
import { TiltCard } from "@/components/ui/card";

/** A demo card using the REAL TiltCard export, with count-up + progress. */
function DemoCard({ title, value, index }: { title: string; value: number; index: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const controls = animate(0, value, {
      duration: 1.1,
      delay: 0.15 + index * 0.08,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [value, index]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 28, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      transition={{ duration: 0.7, delay: index * 0.08, ease: [0.22, 1, 0.36, 1] }}
    >
      <TiltCard>
        <div style={{ padding: "1.5rem 1.6rem", transform: "translateZ(40px)" }}>
          <p className="dept-label">{title}</p>
          <p className="intaglio figure" style={{ fontSize: "clamp(2rem,4vw,2.8rem)", marginTop: ".4rem" }}>
            ${display.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
          <div style={{ marginTop: ".7rem", height: 6, background: "hsl(var(--rule-strong)/.2)", position: "relative", overflow: "hidden" }}>
            <motion.div
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 0.4 + index * 0.18 }}
              transition={{ duration: 1, delay: 0.3 + index * 0.08, ease: [0.22, 1, 0.36, 1] }}
              style={{ transformOrigin: "left", position: "absolute", inset: 0, background: "hsl(var(--gold))" }}
            />
          </div>
        </div>
      </TiltCard>
    </motion.div>
  );
}

export default function AtlasPreview() {
  const [dark, setDark] = useState(true);
  const heroRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  // a big count-up hero number
  const [hero, setHero] = useState(0);
  useEffect(() => {
    const c = animate(0, 4210.18, {
      duration: 1.6,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setHero(v),
    });
    return () => c.stop();
  }, []);

  const cards = [
    { title: "Safe to Spend", value: 612.4 },
    { title: "Net Worth", value: 35598.18 },
    { title: "Budget Status", value: 2986.0 },
    { title: "This Month", value: 1574.5 },
  ];

  return (
    <div style={{ minHeight: "100vh", padding: "3rem clamp(1rem,5vw,4rem) 8rem", position: "relative" }}>
      <GuillocheGL opacity={dark ? 0.55 : 0.4} />
      <BurinCursor />

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1100, margin: "0 auto" }}>
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          <p className="dept-label">Department of Personal Accounts · Atlas (powered)</p>
          <button
            onClick={() => setDark((d) => !d)}
            className="press"
            style={{
              float: "right",
              fontFamily: "'Spline Sans Mono',monospace",
              fontSize: ".72rem",
              padding: ".35rem .7rem",
              border: "1px solid hsl(var(--rule-strong)/.5)",
              background: "transparent",
              color: "hsl(var(--foreground))",
            }}
          >
            ◐ {dark ? "dark" : "light"}
          </button>
        </motion.div>

        {/* HERO */}
        <div ref={heroRef} style={{ margin: "1.5rem 0 2.5rem" }}>
          <p className="dept-label">Projected balance · Form 90</p>
          <motion.p
            initial={{ opacity: 0, filter: "blur(10px)" }}
            animate={{ opacity: 1, filter: "blur(0px)" }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
            className="intaglio figure"
            style={{
              fontSize: "clamp(3rem,9vw,6rem)",
              lineHeight: 1,
              textShadow: dark
                ? "0 0 38px hsl(var(--gold) / 0.28)"
                : "0 1px 0 hsl(var(--paper-high))",
            }}
          >
            $
            {hero.toLocaleString("en-US", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </motion.p>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6, duration: 0.6 }}
            style={{ color: "hsl(var(--muted-foreground))", marginTop: ".6rem" }}
          >
            Move your mouse — the engraving flows toward your cursor. Hover a plate to tilt it.
          </motion.p>
        </div>

        {/* TILT CARDS */}
        <div
          style={{
            display: "grid",
            gap: "1.4rem",
            gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))",
          }}
        >
          {cards.map((c, i) => (
            <DemoCard key={c.title} title={c.title} value={c.value} index={i} />
          ))}
        </div>
      </div>
    </div>
  );
}
