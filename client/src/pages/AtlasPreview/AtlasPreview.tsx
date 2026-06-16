/**
 * THROWAWAY dev preview (frontend-elevation) — POWERED + drama, palette compare.
 * Light "Ledger Paper" vs a refined dark (cleaner near-black, brighter cards) so
 * we can pick. Drama: WebGL guilloché + gold dust + animated light-wash +
 * parallax + scroll-driven reveals. Remove after review.
 */
import { useEffect, useRef, useState } from "react";
import {
  motion,
  animate,
  useScroll,
  useTransform,
  useSpring,
} from "motion/react";
import { GuillocheGL } from "@/components/atlas/GuillocheGL";
import { GoldDust } from "@/components/atlas/GoldDust";
import { BurinCursor } from "@/components/atlas/BurinCursor";
import { TiltCard } from "@/components/ui/card";

/** Refined-dark var overrides: deeper, less-murky base + brighter, crisper cards. */
const REFINED_DARK: React.CSSProperties = {
  // a near-black with the faintest teal, not the muddy olive of the default dark
  ["--background" as string]: "200 18% 5%",
  ["--card" as string]: "195 16% 11%",
  ["--rule-strong" as string]: "180 14% 42%",
  ["--paper-high" as string]: "190 30% 16%",
  ["--muted-foreground" as string]: "180 12% 62%",
};

function DemoCard({ title, value, index }: { title: string; value: number; index: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const c = animate(0, value, {
      duration: 1.1,
      delay: 0.1 + index * 0.07,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => c.stop();
  }, [value, index]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 30, filter: "blur(6px)" }}
      whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.7, delay: index * 0.06, ease: [0.22, 1, 0.36, 1] }}
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
              whileInView={{ scaleX: 0.4 + index * 0.15 }}
              viewport={{ once: true }}
              transition={{ duration: 1, delay: 0.2 + index * 0.06, ease: [0.22, 1, 0.36, 1] }}
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
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  // Parallax: hero drifts up + fades as you scroll; light-wash drifts opposite.
  const { scrollY } = useScroll();
  const heroY = useSpring(useTransform(scrollY, [0, 500], [0, -90]), { stiffness: 80, damping: 20 });
  const heroOpacity = useTransform(scrollY, [0, 360], [1, 0.15]);
  const washY = useTransform(scrollY, [0, 800], [0, 160]);

  const [hero, setHero] = useState(0);
  useEffect(() => {
    const c = animate(0, 4210.18, { duration: 1.6, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => setHero(v) });
    return () => c.stop();
  }, []);

  const cards = [
    { title: "Safe to Spend", value: 612.4 },
    { title: "Net Worth", value: 35598.18 },
    { title: "Budget Status", value: 2986.0 },
    { title: "This Month", value: 1574.5 },
    { title: "Emergency Fund", value: 1800.0 },
    { title: "Subscriptions", value: 214.0 },
  ];

  return (
    <div
      ref={scrollRef}
      style={{
        minHeight: "200vh",
        padding: "3rem clamp(1rem,5vw,4rem) 12rem",
        position: "relative",
        ...(dark ? REFINED_DARK : {}),
        background: "hsl(var(--background))",
      }}
    >
      {/* DRAMA STACK (behind content) */}
      <GuillocheGL opacity={dark ? 0.5 : 0.4} />
      <GoldDust count={dark ? 70 : 40} opacity={dark ? 0.6 : 0.4} />
      {/* animated light-wash: a slow aurora sweep */}
      <motion.div
        aria-hidden
        style={{
          position: "fixed",
          inset: "-20% -20% auto -20%",
          height: "70vh",
          y: washY,
          zIndex: 0,
          pointerEvents: "none",
          background:
            "radial-gradient(60% 50% at 30% 0%, hsl(var(--gold) / 0.10), transparent 70%), radial-gradient(50% 50% at 80% 10%, hsl(var(--primary) / 0.12), transparent 70%)",
          filter: "blur(20px)",
        }}
        animate={{ opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
      />
      <BurinCursor />

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1100, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <p className="dept-label">Department of Personal Accounts · Atlas (powered + drama)</p>
          <button
            onClick={() => setDark((d) => !d)}
            className="press"
            style={{
              fontFamily: "'Spline Sans Mono',monospace",
              fontSize: ".72rem",
              padding: ".35rem .7rem",
              border: "1px solid hsl(var(--rule-strong)/.5)",
              background: "transparent",
              color: "hsl(var(--foreground))",
            }}
          >
            ◐ {dark ? "refined dark" : "light paper"}
          </button>
        </div>

        {/* HERO with parallax */}
        <motion.div style={{ y: heroY, opacity: heroOpacity, margin: "2rem 0 3rem" }}>
          <p className="dept-label">Projected balance · Form 90</p>
          <motion.p
            initial={{ opacity: 0, filter: "blur(12px)", y: 12 }}
            animate={{ opacity: 1, filter: "blur(0px)", y: 0 }}
            transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }}
            className="intaglio figure"
            style={{
              fontSize: "clamp(3.2rem,10vw,6.5rem)",
              lineHeight: 1,
              textShadow: dark ? "0 0 44px hsl(var(--gold) / 0.30)" : "0 1px 0 hsl(var(--paper-high))",
            }}
          >
            ${hero.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </motion.p>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5, duration: 0.6 }}
            style={{ color: "hsl(var(--muted-foreground))", marginTop: ".7rem", fontSize: "1.05rem" }}
          >
            Move your mouse — the engraving flows, dust drifts, plates tilt. Scroll to reveal.
          </motion.p>
        </motion.div>

        <div style={{ display: "grid", gap: "1.4rem", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))" }}>
          {cards.map((c, i) => (
            <DemoCard key={c.title} title={c.title} value={c.value} index={i} />
          ))}
        </div>

        {/* a second band lower down to show scroll-reveals firing on scroll */}
        <motion.h2
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="font-display"
          style={{ fontSize: "clamp(1.6rem,4vw,2.4rem)", margin: "5rem 0 1.5rem" }}
        >
          Schedule of Standing Orders
        </motion.h2>
        <div style={{ display: "grid", gap: "1.4rem", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))" }}>
          {cards.slice(0, 3).map((c, i) => (
            <DemoCard key={"b" + c.title} title={c.title} value={c.value} index={i} />
          ))}
        </div>
      </div>
    </div>
  );
}
