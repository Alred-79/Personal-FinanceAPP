/**
 * THROWAWAY dev gallery (frontend-elevation) — four DISTINCT visual directions
 * to compare, each rich with components. Switch at top. Remove after review.
 * Self-contained inline styles (exploration code, not production).
 */
import { useEffect, useState } from "react";
import { motion, animate, useMotionValue, useSpring, useMotionTemplate } from "motion/react";

/* ---------- shared tiny helpers ---------- */
function useCountUp(to: number, delay = 0) {
  const [v, setV] = useState(0);
  useEffect(() => {
    const c = animate(0, to, { duration: 1.3, delay, ease: [0.22, 1, 0.36, 1], onUpdate: setV });
    return () => c.stop();
  }, [to, delay]);
  return v;
}
const money = (v: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function Spark({ color, w = 90, h = 26 }: { color: string; w?: number; h?: number }) {
  const pts = [6, 9, 7, 12, 10, 15, 13, 18, 16, 22, 20];
  const max = Math.max(...pts), min = Math.min(...pts);
  const d = pts
    .map((p, i) => `${(i / (pts.length - 1)) * w},${h - ((p - min) / (max - min)) * h}`)
    .join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline points={d} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

function Gauge({ pct, color, label }: { pct: number; color: string; label: string }) {
  const r = 34, c = 2 * Math.PI * r;
  return (
    <div style={{ textAlign: "center" }}>
      <svg width={86} height={86}>
        <circle cx={43} cy={43} r={r} fill="none" stroke={color} strokeOpacity={0.15} strokeWidth={7} />
        <motion.circle
          cx={43} cy={43} r={r} fill="none" stroke={color} strokeWidth={7} strokeLinecap="round"
          strokeDasharray={c} transform="rotate(-90 43 43)"
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - pct) }}
          transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1] }}
          style={{ filter: `drop-shadow(0 0 6px ${color})` }}
        />
        <text x={43} y={48} textAnchor="middle" fill={color} fontFamily="'Spline Sans Mono',monospace" fontSize={15}>
          {Math.round(pct * 100)}
        </text>
      </svg>
      <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".6rem", letterSpacing: ".15em", opacity: 0.7 }}>
        {label}
      </div>
    </div>
  );
}

/* =====================================================================
   1. MISSION CONTROL — deep space-black, cyan/lime, dense data cockpit
   ===================================================================== */
function MissionControl() {
  const nw = useCountUp(35598.18);
  const s2s = useCountUp(612.4, 0.1);
  const bg = "#05080b", cyan = "#22d3ee", lime = "#a3e635", mag = "#f472b6", ink = "#cbd5e1";
  return (
    <div style={{ background: bg, color: ink, minHeight: "100vh", fontFamily: "'Spline Sans Mono',monospace", padding: "1.5rem clamp(1rem,4vw,3rem)" }}>
      {/* top status bar */}
      <div style={{ display: "flex", gap: "1.5rem", alignItems: "center", borderBottom: `1px solid ${cyan}33`, paddingBottom: ".8rem", fontSize: ".72rem", letterSpacing: ".1em" }}>
        <span style={{ color: lime }}>● LIVE</span>
        <span style={{ color: cyan }}>ATLAS // MISSION CONTROL</span>
        <span style={{ marginLeft: "auto", overflow: "hidden", whiteSpace: "nowrap", color: ink, opacity: 0.7 }}>
          AAPL ▲2.1  ·  GROCERIES −$84.20  ·  PAYROLL +$2,400  ·  CON ED −$140  ·  RENT due 5d
        </span>
      </div>

      {/* hero readout */}
      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: "1.5rem", margin: "1.5rem 0" }}>
        <div style={{ border: `1px solid ${cyan}33`, padding: "1.4rem", position: "relative", background: "linear-gradient(180deg,#0a1016,#05080b)" }}>
          <div style={{ fontSize: ".66rem", letterSpacing: ".22em", color: cyan, opacity: 0.8 }}>NET WORTH · REALTIME</div>
          <div style={{ fontSize: "clamp(2.4rem,6vw,4rem)", color: "#fff", textShadow: `0 0 30px ${cyan}66`, fontWeight: 600 }}>
            ${money(nw)}
          </div>
          <div style={{ display: "flex", gap: "1rem", alignItems: "center", marginTop: ".4rem" }}>
            <span style={{ color: lime }}>▲ +2.43%</span>
            <Spark color={lime} w={160} />
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          {[["SAFE-TO-SPEND", `$${money(s2s)}`, cyan], ["OVERDRAFT RISK", "27%", mag], ["BURN/DAY", "$63.40", lime], ["RUNWAY", "41d", cyan]].map(([l, v, col]) => (
            <div key={l} style={{ border: `1px solid ${col}33`, padding: ".8rem", background: "#0a1016" }}>
              <div style={{ fontSize: ".58rem", letterSpacing: ".16em", opacity: 0.7 }}>{l}</div>
              <div style={{ fontSize: "1.3rem", color: col as string, textShadow: `0 0 12px ${col}55` }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      {/* gauges + bars + command */}
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: "1.5rem", alignItems: "center", border: `1px solid ${cyan}22`, padding: "1.2rem", background: "#0a1016" }}>
        <div style={{ display: "flex", gap: "1rem" }}>
          <Gauge pct={0.78} color={cyan} label="BUDGET" />
          <Gauge pct={0.42} color={lime} label="GOALS" />
          <Gauge pct={0.27} color={mag} label="RISK" />
        </div>
        <div style={{ display: "flex", gap: ".4rem", alignItems: "flex-end", height: 90 }}>
          {[40, 65, 30, 80, 55, 70, 45, 90, 60, 35, 75, 50].map((h, i) => (
            <motion.div key={i} initial={{ height: 0 }} animate={{ height: `${h}%` }} transition={{ delay: i * 0.04, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              style={{ flex: 1, background: `linear-gradient(${cyan},${cyan}22)`, boxShadow: `0 0 8px ${cyan}55` }} />
          ))}
        </div>
        <div style={{ minWidth: 180 }}>
          <div style={{ fontSize: ".6rem", letterSpacing: ".16em", color: cyan, marginBottom: ".4rem" }}>COMMAND</div>
          <div style={{ border: `1px solid ${cyan}55`, padding: ".5rem .7rem", color: "#fff" }}>
            &gt; fund emergency<span style={{ animation: "blink 1s step-end infinite", color: lime }}>_</span>
          </div>
          <div style={{ fontSize: ".58rem", opacity: 0.6, marginTop: ".5rem" }}>⌘K · 14 actions ready</div>
        </div>
      </div>
      <style>{`@keyframes blink{50%{opacity:0}}`}</style>
    </div>
  );
}

/* =====================================================================
   2. AURORA GLASS — living gradient mesh, frosted glass panels
   ===================================================================== */
function AuroraGlass() {
  const nw = useCountUp(35598.18);
  return (
    <div style={{ position: "relative", minHeight: "100vh", overflow: "hidden", padding: "3rem clamp(1rem,5vw,4rem)", fontFamily: "'Instrument Sans',system-ui,sans-serif", color: "#0b1020" }}>
      {/* aurora mesh */}
      {[
        { c: "rgba(139,92,246,0.55)", x: "10%", y: "10%", d: 0 },
        { c: "rgba(45,212,191,0.5)", x: "75%", y: "20%", d: 3 },
        { c: "rgba(244,114,182,0.45)", x: "40%", y: "70%", d: 6 },
        { c: "rgba(56,189,248,0.5)", x: "85%", y: "75%", d: 2 },
      ].map((b, i) => (
        <motion.div key={i} aria-hidden
          animate={{ x: [0, 40, -20, 0], y: [0, -30, 20, 0] }}
          transition={{ duration: 14 + b.d, repeat: Infinity, ease: "easeInOut" }}
          style={{ position: "absolute", left: b.x, top: b.y, width: 480, height: 480, borderRadius: "50%", background: b.c, filter: "blur(90px)" }} />
      ))}
      <div style={{ position: "absolute", inset: 0, background: "rgba(248,250,255,0.4)" }} />

      <div style={{ position: "relative", maxWidth: 1080, margin: "0 auto" }}>
        <p style={{ fontSize: ".7rem", letterSpacing: ".3em", textTransform: "uppercase", opacity: 0.6 }}>Atlas · Aurora</p>
        {/* hero glass */}
        <div style={glass(28)}>
          <p style={{ fontSize: ".75rem", letterSpacing: ".2em", textTransform: "uppercase", opacity: 0.6 }}>Net Worth</p>
          <p style={{ fontSize: "clamp(2.6rem,7vw,4.4rem)", fontWeight: 600, margin: ".2rem 0", letterSpacing: "-0.02em" }}>${money(nw)}</p>
          <p style={{ color: "#0e9f6e", fontWeight: 600 }}>▲ +2.4% this month</p>
        </div>
        {/* glass stat row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: "1.2rem", marginTop: "1.2rem" }}>
          {[["Safe to Spend", "$612.40"], ["Emergency", "$1,800.00"], ["Budget", "78% used"], ["This Month", "$1,574.50"]].map(([l, v], i) => (
            <motion.div key={l} initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.08, duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
              style={glass(20)}>
              <p style={{ fontSize: ".72rem", letterSpacing: ".12em", textTransform: "uppercase", opacity: 0.55 }}>{l}</p>
              <p style={{ fontSize: "1.8rem", fontWeight: 600, marginTop: ".3rem" }}>{v}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
  function glass(radius: number): React.CSSProperties {
    return {
      background: "rgba(255,255,255,0.45)",
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
      border: "1px solid rgba(255,255,255,0.6)",
      borderRadius: radius,
      padding: "1.6rem 1.8rem",
      boxShadow: "0 20px 50px rgba(20,20,60,0.12)",
      marginTop: "1.2rem",
    };
  }
}

/* =====================================================================
   3. SPATIAL 3D — floating panels in depth, orbiting centerpiece, parallax
   ===================================================================== */
function Spatial3D() {
  const rx = useSpring(useMotionValue(0), { stiffness: 60, damping: 14 });
  const ry = useSpring(useMotionValue(0), { stiffness: 60, damping: 14 });
  const transform = useMotionTemplate`rotateX(${rx}deg) rotateY(${ry}deg)`;
  function onMove(e: React.PointerEvent) {
    const px = e.clientX / window.innerWidth, py = e.clientY / window.innerHeight;
    ry.set((px - 0.5) * 18);
    rx.set((0.5 - py) * 18);
  }
  const nw = useCountUp(35598.18);
  const panel = (x: number, y: number, z: number, big = false): React.CSSProperties => ({
    position: "absolute", left: `calc(50% + ${x}px)`, top: `calc(50% + ${y}px)`,
    transform: `translate(-50%,-50%) translateZ(${z}px)`,
    background: "rgba(20,28,52,0.55)", border: "1px solid rgba(120,160,255,0.3)",
    backdropFilter: "blur(8px)", borderRadius: 14, padding: big ? "1.6rem 2rem" : "1rem 1.3rem",
    boxShadow: "0 30px 60px rgba(0,0,0,0.5)", color: "#dbe4ff", minWidth: big ? 280 : 150,
  });
  return (
    <div onPointerMove={onMove} style={{ minHeight: "100vh", background: "radial-gradient(circle at 50% 40%,#1a2348,#0a0e1f 70%)", overflow: "hidden", perspective: 1200, fontFamily: "'Instrument Sans',system-ui" }}>
      <motion.div style={{ position: "absolute", inset: 0, transformStyle: "preserve-3d", transform }}>
        {/* orbiting rings centerpiece */}
        <div style={{ position: "absolute", left: "50%", top: "50%", transform: "translate(-50%,-50%)", transformStyle: "preserve-3d" }}>
          {[0, 1, 2].map((i) => (
            <motion.div key={i} animate={{ rotateZ: 360 }} transition={{ duration: 14 + i * 6, repeat: Infinity, ease: "linear" }}
              style={{ position: "absolute", left: "50%", top: "50%", width: 240 + i * 90, height: 240 + i * 90, marginLeft: -(120 + i * 45), marginTop: -(120 + i * 45), border: `1px solid rgba(${i === 0 ? "245,200,80" : "120,160,255"},0.4)`, borderRadius: "50%", boxShadow: `0 0 20px rgba(120,160,255,0.2)`, transform: `rotateX(${60 + i * 8}deg)` }} />
          ))}
          <div style={{ position: "absolute", left: "50%", top: "50%", transform: "translate(-50%,-50%) translateZ(40px)", textAlign: "center" }}>
            <div style={{ fontSize: ".66rem", letterSpacing: ".22em", color: "#9fb4ff" }}>NET WORTH</div>
            <div style={{ fontSize: "2.6rem", fontWeight: 700, color: "#fff", textShadow: "0 0 30px rgba(245,200,80,0.5)" }}>${money(nw)}</div>
          </div>
        </div>
        {/* floating panels at depth */}
        <div style={panel(-360, -150, 60)}>
          <div style={{ fontSize: ".66rem", letterSpacing: ".16em", opacity: 0.7 }}>SAFE TO SPEND</div>
          <div style={{ fontSize: "1.7rem", fontWeight: 600 }}>$612.40</div>
        </div>
        <div style={panel(360, -90, 30)}>
          <div style={{ fontSize: ".66rem", letterSpacing: ".16em", opacity: 0.7 }}>BUDGET USED</div>
          <div style={{ fontSize: "1.7rem", fontWeight: 600 }}>78%</div>
        </div>
        <div style={panel(-300, 180, 90)}>
          <div style={{ fontSize: ".66rem", letterSpacing: ".16em", opacity: 0.7 }}>EMERGENCY</div>
          <div style={{ fontSize: "1.7rem", fontWeight: 600 }}>$1,800.00</div>
        </div>
        <div style={panel(330, 170, 50)}>
          <div style={{ fontSize: ".66rem", letterSpacing: ".16em", opacity: 0.7 }}>OVERDRAFT RISK</div>
          <div style={{ fontSize: "1.7rem", fontWeight: 600, color: "#f9a8d4" }}>27%</div>
        </div>
      </motion.div>
      <div style={{ position: "absolute", bottom: 24, left: 0, right: 0, textAlign: "center", color: "#9fb4ff", fontSize: ".72rem", letterSpacing: ".2em" }}>
        ATLAS · SPATIAL — move cursor to orbit
      </div>
    </div>
  );
}

/* =====================================================================
   4. EDITORIAL BOLD — huge type, asymmetric grid, vivid accent blocks
   ===================================================================== */
function EditorialBold() {
  const nw = useCountUp(35598.18);
  const paper = "#f4f1e8", ink = "#14140f", accent = "#ff4d2e", cobalt = "#1f3df0";
  return (
    <div style={{ minHeight: "100vh", background: paper, color: ink, padding: "3rem clamp(1rem,5vw,5rem)", fontFamily: "'Instrument Sans',system-ui" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: ".7rem", letterSpacing: ".3em", textTransform: "uppercase", borderBottom: `2px solid ${ink}`, paddingBottom: ".6rem" }}>
        <span>The Atlas Ledger</span><span>No. 04 · 2026</span>
      </div>
      {/* giant hero */}
      <motion.div initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }} style={{ margin: "1.5rem 0 1rem" }}>
        <div style={{ fontSize: ".85rem", letterSpacing: ".2em", textTransform: "uppercase", color: accent, fontWeight: 700 }}>Net Worth</div>
        <div style={{ fontFamily: "'Fraunces',Georgia,serif", fontWeight: 600, fontSize: "clamp(3.5rem,13vw,9rem)", lineHeight: 0.92, letterSpacing: "-0.03em" }}>
          ${money(nw)}
        </div>
      </motion.div>
      {/* asymmetric grid of blocks */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gridAutoRows: "minmax(120px,auto)", gap: "1px", background: ink, border: `2px solid ${ink}` }}>
        <div style={{ background: accent, color: paper, padding: "1.4rem", gridRow: "span 2", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <span style={{ letterSpacing: ".16em", textTransform: "uppercase", fontSize: ".7rem", fontWeight: 700 }}>Safe to Spend</span>
          <span style={{ fontFamily: "'Fraunces',serif", fontSize: "clamp(2rem,5vw,3.4rem)", fontWeight: 600 }}>$612.40</span>
        </div>
        {[["Budget", "78%", paper, ink], ["Risk", "27%", cobalt, paper], ["Emergency", "$1,800", paper, ink], ["This Month", "$1,574", ink, paper]].map(([l, v, b, c]) => (
          <div key={l as string} style={{ background: b as string, color: c as string, padding: "1.2rem", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <span style={{ letterSpacing: ".16em", textTransform: "uppercase", fontSize: ".66rem", fontWeight: 700 }}>{l}</span>
            <span style={{ fontFamily: "'Fraunces',serif", fontSize: "1.9rem", fontWeight: 600 }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- gallery shell ---------- */
const DIRECTIONS = [
  { key: "mission", label: "Mission Control", el: <MissionControl /> },
  { key: "aurora", label: "Aurora Glass", el: <AuroraGlass /> },
  { key: "spatial", label: "Spatial 3D", el: <Spatial3D /> },
  { key: "editorial", label: "Editorial Bold", el: <EditorialBold /> },
];

export default function DirectionsGallery() {
  const [active, setActive] = useState("mission");
  return (
    <div style={{ position: "relative" }}>
      <div style={{ position: "fixed", top: 12, left: "50%", transform: "translateX(-50%)", zIndex: 100, display: "flex", gap: ".4rem", background: "rgba(0,0,0,0.6)", backdropFilter: "blur(10px)", padding: ".4rem", borderRadius: 10 }}>
        {DIRECTIONS.map((d) => (
          <button key={d.key} onClick={() => setActive(d.key)}
            style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".72rem", padding: ".4rem .8rem", border: "none", borderRadius: 6, cursor: "pointer", background: active === d.key ? "#fff" : "transparent", color: active === d.key ? "#000" : "#fff" }}>
            {d.label}
          </button>
        ))}
      </div>
      {DIRECTIONS.find((d) => d.key === active)?.el}
    </div>
  );
}
