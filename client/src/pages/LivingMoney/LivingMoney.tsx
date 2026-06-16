/**
 * THE LIVING LEDGER (frontend-elevation showpiece) — your money as a living
 * organism. A molten-gold core (net worth, breathing) tethered by ELASTIC gold
 * threads to draggable satellite nodes (goals/accounts/bills). Grab a node and
 * fling it — the thread stretches, it springs back into orbit. The cursor pulls
 * everything. A flowing WebGL guilloché breathes behind it.
 *
 * THROWAWAY dev route (/living). OPEN IT AND DRAG THE NODES — static screenshots
 * cannot convey the physics. Remove after review.
 */
import { useEffect, useRef, useState } from "react";
import { motion, animate, useMotionValue, useSpring } from "motion/react";
import { GuillocheGL } from "@/components/atlas/GuillocheGL";

type Node = {
  id: string;
  label: string;
  value: string;
  angle: number; // orbit position (deg)
  dist: number; // orbit radius (px)
  size: number;
  tone: "gold" | "credit" | "debit";
};

const NODES: Node[] = [
  { id: "s2s", label: "Safe to Spend", value: "$612", angle: -90, dist: 230, size: 96, tone: "gold" },
  { id: "emg", label: "Emergency", value: "$1,800", angle: -25, dist: 300, size: 112, tone: "credit" },
  { id: "veh", label: "Car Fund", value: "$4,100", angle: 35, dist: 250, size: 90, tone: "credit" },
  { id: "rent", label: "Rent · due 5d", value: "−$1,450", angle: 100, dist: 300, size: 104, tone: "debit" },
  { id: "subs", label: "Subscriptions", value: "−$214", angle: 160, dist: 240, size: 84, tone: "debit" },
  { id: "pay", label: "Payroll", value: "+$2,400", angle: 215, dist: 300, size: 96, tone: "credit" },
];

export default function LivingMoney() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const coreRef = useRef<HTMLDivElement>(null);
  const threadsRef = useRef<HTMLCanvasElement>(null);
  const nodeRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // parallax of the whole system toward the cursor (subtle)
  const px = useSpring(useMotionValue(0), { stiffness: 50, damping: 18 });
  const py = useSpring(useMotionValue(0), { stiffness: 50, damping: 18 });

  const [nw, setNw] = useState(0);
  useEffect(() => {
    const c = animate(0, 35598.18, { duration: 1.8, ease: [0.22, 1, 0.36, 1], onUpdate: setNw });
    return () => c.stop();
  }, []);

  // elastic threads: redraw each frame from live DOM positions
  useEffect(() => {
    const canvas = threadsRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      canvas!.width = wrap!.clientWidth * DPR;
      canvas!.height = wrap!.clientHeight * DPR;
      canvas!.style.width = wrap!.clientWidth + "px";
      canvas!.style.height = wrap!.clientHeight + "px";
    }
    resize();
    window.addEventListener("resize", resize);

    const gold = () =>
      `hsl(${getComputedStyle(document.documentElement).getPropertyValue("--gold").trim()})`;

    let raf = 0;
    let running = true;
    let t = 0;
    function center(el: Element) {
      const r = el.getBoundingClientRect();
      const w = wrap!.getBoundingClientRect();
      return { x: (r.left + r.width / 2 - w.left) * DPR, y: (r.top + r.height / 2 - w.top) * DPR };
    }
    function frame() {
      if (!running) return;
      t += 0.02;
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height);
      const core = coreRef.current;
      if (!core) { raf = requestAnimationFrame(frame); return; }
      const c = center(core);
      const g = gold();
      for (const n of NODES) {
        const el = nodeRefs.current[n.id];
        if (!el) continue;
        const p = center(el);
        // a gently waving bezier between core and node (elastic feel)
        const midx = (c.x + p.x) / 2 + Math.sin(t + n.angle) * 14 * DPR;
        const midy = (c.y + p.y) / 2 + Math.cos(t + n.angle) * 14 * DPR;
        const dist = Math.hypot(p.x - c.x, p.y - c.y);
        const slack = Math.min(1, dist / (520 * DPR)); // thread brightens as it stretches
        ctx!.strokeStyle = g;
        ctx!.globalAlpha = 0.25 + slack * 0.5;
        ctx!.lineWidth = (0.6 + (1 - slack) * 1.2) * DPR;
        ctx!.beginPath();
        ctx!.moveTo(c.x, c.y);
        ctx!.quadraticCurveTo(midx, midy, p.x, p.y);
        ctx!.stroke();
        // a faint parallel line for the engraved double-rule feel
        ctx!.globalAlpha = 0.12;
        ctx!.lineWidth = 0.5 * DPR;
        ctx!.beginPath();
        ctx!.moveTo(c.x, c.y);
        ctx!.quadraticCurveTo(midx + 3 * DPR, midy + 3 * DPR, p.x, p.y);
        ctx!.stroke();
      }
      ctx!.globalAlpha = 1;
      raf = requestAnimationFrame(frame);
    }
    frame();
    function onVis() {
      if (document.hidden) { running = false; cancelAnimationFrame(raf); }
      else { running = true; frame(); }
    }
    document.addEventListener("visibilitychange", onVis);
    return () => {
      running = false;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  // cursor parallax
  function onPointerMove(e: React.PointerEvent) {
    const w = wrapRef.current!.getBoundingClientRect();
    px.set(((e.clientX - w.left) / w.width - 0.5) * 26);
    py.set(((e.clientY - w.top) / w.height - 0.5) * 26);
  }

  const toneColor = (tone: Node["tone"]) =>
    tone === "debit" ? "var(--debit)" : tone === "credit" ? "var(--credit)" : "var(--gold)";

  return (
    <div
      ref={wrapRef}
      onPointerMove={onPointerMove}
      style={{
        position: "relative",
        minHeight: "100vh",
        overflow: "hidden",
        background: "radial-gradient(circle at 50% 45%, #10171d, #06090c 70%)",
        fontFamily: "'Instrument Sans', system-ui, sans-serif",
        ["--gold" as string]: "42 70% 58%",
        ["--credit" as string]: "156 50% 60%",
        ["--debit" as string]: "8 75% 64%",
      }}
    >
      <GuillocheGL opacity={0.42} />
      {/* threads canvas above guilloché, below nodes */}
      <canvas ref={threadsRef} aria-hidden style={{ position: "absolute", inset: 0, zIndex: 1, pointerEvents: "none" }} />

      {/* header */}
      <div style={{ position: "absolute", top: 24, left: 28, zIndex: 5, color: "#9fb0bb", fontFamily: "'Spline Sans Mono',monospace", fontSize: ".72rem", letterSpacing: ".24em" }}>
        ATLAS · THE LIVING LEDGER
      </div>
      <div style={{ position: "absolute", top: 24, right: 28, zIndex: 5, color: "#6b7d88", fontFamily: "'Spline Sans Mono',monospace", fontSize: ".7rem" }}>
        drag a node · fling it · watch it spring back
      </div>

      {/* the system */}
      <motion.div
        style={{ position: "absolute", inset: 0, zIndex: 2, x: px, y: py }}
      >
        <div style={{ position: "absolute", left: "50%", top: "50%", transform: "translate(-50%,-50%)" }}>
          {/* CORE */}
          <motion.div
            ref={coreRef}
            animate={{ scale: [1, 1.04, 1] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            style={{
              position: "relative",
              width: 230,
              height: 230,
              borderRadius: "50%",
              display: "grid",
              placeItems: "center",
              background: "radial-gradient(circle at 38% 32%, hsl(42 85% 70%), hsl(40 70% 38%) 70%, hsl(38 60% 26%))",
              boxShadow: "0 0 90px hsl(42 80% 55% / 0.45), inset 0 0 40px hsl(40 60% 20% / 0.6), inset 0 0 0 2px hsl(46 60% 92% / 0.25)",
              zIndex: 3,
            }}
          >
            {/* guilloché ring */}
            <div style={{ position: "absolute", inset: -14, borderRadius: "50%", border: "1px solid hsl(46 60% 92% / 0.25)" }} />
            <div style={{ textAlign: "center", color: "#1c1408" }}>
              <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".62rem", letterSpacing: ".26em", opacity: 0.7 }}>NET WORTH</div>
              <div style={{ fontFamily: "'Fraunces',Georgia,serif", fontWeight: 600, fontSize: "2.1rem", lineHeight: 1, marginTop: 2 }}>
                ${nw.toLocaleString("en-US", { maximumFractionDigits: 0 })}
              </div>
            </div>
          </motion.div>

          {/* NODES */}
          {NODES.map((n) => {
            const rad = (n.angle * Math.PI) / 180;
            const ox = Math.cos(rad) * n.dist;
            const oy = Math.sin(rad) * n.dist;
            return (
              <div
                key={n.id}
                style={{ position: "absolute", left: ox, top: oy, transform: "translate(-50%,-50%)" }}
              >
                {/* idle float wrapper */}
                <motion.div
                  animate={{ y: [0, -8, 0] }}
                  transition={{ duration: 3 + n.dist / 120, repeat: Infinity, ease: "easeInOut" }}
                >
                  <motion.div
                    ref={(el) => { nodeRefs.current[n.id] = el; }}
                    drag
                    dragSnapToOrigin
                    dragElastic={0.5}
                    whileDrag={{ scale: 1.12, zIndex: 10 }}
                    whileHover={{ scale: 1.06 }}
                    style={{
                      width: n.size,
                      height: n.size,
                      borderRadius: "50%",
                      display: "grid",
                      placeItems: "center",
                      textAlign: "center",
                      cursor: "grab",
                      background: "radial-gradient(circle at 38% 30%, #15202a, #0c1318)",
                      border: `1px solid hsl(${toneColor(n.tone)} / 0.5)`,
                      boxShadow: `0 10px 30px rgba(0,0,0,0.5), 0 0 26px hsl(${toneColor(n.tone)} / 0.18), inset 0 0 18px hsl(${toneColor(n.tone)} / 0.08)`,
                      color: "#dce6ec",
                    }}
                  >
                    <div style={{ padding: 6 }}>
                      <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".52rem", letterSpacing: ".1em", textTransform: "uppercase", opacity: 0.7 }}>
                        {n.label}
                      </div>
                      <div style={{ fontFamily: "'Fraunces',serif", fontWeight: 600, fontSize: "1.05rem", marginTop: 2, color: `hsl(${toneColor(n.tone)})` }}>
                        {n.value}
                      </div>
                    </div>
                  </motion.div>
                </motion.div>
              </div>
            );
          })}
        </div>
      </motion.div>
    </div>
  );
}
