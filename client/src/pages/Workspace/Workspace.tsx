/**
 * THROWAWAY dev preview (frontend-elevation) — clean dashboard that's ALIVE:
 * digestible info + reactive cursor-following background + cards that POP on
 * hover (lift / scale / gold glow / cursor sheen / tilt) + count-ups + smooth
 * motion on every interaction. WebGL guilloché + Framer Motion. Remove after review.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  motion, AnimatePresence, useMotionValue, useSpring, useMotionTemplate, animate,
} from "motion/react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from "recharts";
import { ink, AXIS_TICK, tooltipStyle } from "@/lib/chart";
import { GuillocheGL } from "@/components/atlas/GuillocheGL";

/* ---------- data ---------- */
const RANGES = ["1W", "1M", "3M", "1Y"] as const;
type Range = (typeof RANGES)[number];
const SERIES: Record<Range, { d: string; v: number }[]> = {
  "1W": gen(7, 4100, 60), "1M": gen(30, 3600, 120), "3M": gen(36, 2900, 200), "1Y": gen(48, 1500, 400),
};
function gen(n: number, base: number, amp: number) {
  const out = []; let v = base;
  for (let i = 0; i < n; i++) { v += (Math.sin(i / 3) * amp) / 3 + (i / n) * amp + (((i * 9301 + 49297) % 233) / 233) * amp - amp / 2; out.push({ d: `${i + 1}`, v: Math.max(200, Math.round(v)) }); }
  return out;
}
const CATS = [
  { key: "all", label: "All" }, { key: "grocery", label: "Groceries" }, { key: "dining", label: "Dining" },
  { key: "utilities", label: "Utilities" }, { key: "transport", label: "Transport" },
];
const BUDGETS = [
  { cat: "Groceries", used: 420, limit: 600 }, { cat: "Dining", used: 280, limit: 300 },
  { cat: "Utilities", used: 140, limit: 250 }, { cat: "Transport", used: 90, limit: 200 },
];
const TXNS = [
  { id: 1, date: "06-12", name: "Whole Foods", cat: "grocery", amt: -84.2, note: "Weekly groceries · 14 items · Visa ••4821" },
  { id: 2, date: "06-11", name: "Payroll", cat: "income", amt: 2400, note: "Acme Corp · direct deposit" },
  { id: 3, date: "06-10", name: "Con Edison", cat: "utilities", amt: -140, note: "Electricity · autopay" },
  { id: 4, date: "06-09", name: "Joe's Pizza", cat: "dining", amt: -22.5, note: "Lunch · contactless" },
  { id: 5, date: "06-08", name: "Uber", cat: "transport", amt: -18.3, note: "Ride · downtown" },
  { id: 6, date: "06-07", name: "Trader Joe's", cat: "grocery", amt: -56.1, note: "Snacks + produce" },
];
const TABS = ["Overview", "Spending", "Cashflow"] as const;

function useCountUp(to: number) {
  const [v, setV] = useState(0);
  useEffect(() => { const c = animate(0, to, { duration: 1.2, ease: [0.22, 1, 0.36, 1], onUpdate: setV }); return () => c.stop(); }, [to]);
  return v;
}

/* ---------- a card that POPS: lift + scale + gold ring + cursor sheen + tilt ---------- */
function PopCard({ children, onHoverChange, style }: { children: React.ReactNode; onHoverChange?: (h: boolean) => void; style?: React.CSSProperties }) {
  const rx = useSpring(useMotionValue(0), { stiffness: 150, damping: 15 });
  const ry = useSpring(useMotionValue(0), { stiffness: 150, damping: 15 });
  const mx = useMotionValue(50); const my = useMotionValue(50);
  const sheen = useMotionTemplate`radial-gradient(340px circle at ${mx}% ${my}%, hsl(var(--gold) / 0.16), transparent 60%)`;
  return (
    <motion.div
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
        ry.set((px - 0.5) * 6); rx.set((0.5 - py) * 6); mx.set(px * 100); my.set(py * 100);
      }}
      onPointerEnter={() => onHoverChange?.(true)}
      onPointerLeave={() => { rx.set(0); ry.set(0); onHoverChange?.(false); }}
      whileHover={{ y: -6, scale: 1.025, boxShadow: "0 24px 60px hsl(167 40% 12% / 0.18)" }}
      transition={{ type: "spring", stiffness: 300, damping: 22 }}
      className="plate"
      style={{ position: "relative", rotateX: rx, rotateY: ry, transformPerspective: 1000, transformStyle: "preserve-3d", ...style }}
    >
      <motion.div aria-hidden style={{ position: "absolute", inset: 0, background: sheen, pointerEvents: "none", zIndex: 1 }} />
      <div style={{ position: "relative", zIndex: 2 }}>{children}</div>
    </motion.div>
  );
}

export default function Workspace() {
  const [range, setRange] = useState<Range>("1M");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [cat, setCat] = useState("all");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [hovered, setHovered] = useState<string | null>(null);
  // Real themes only now: Ledger Paper (light) + Midnight (dark, the shipped .dark).
  const [dark, setDark] = useState(false);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  // cursor-following background glow
  const gx = useSpring(useMotionValue(50), { stiffness: 60, damping: 20 });
  const gy = useSpring(useMotionValue(30), { stiffness: 60, damping: 20 });
  const bgGlow = useMotionTemplate`radial-gradient(600px circle at ${gx}% ${gy}%, hsl(var(--gold) / 0.10), transparent 60%)`;
  const wrapRef = useRef<HTMLDivElement>(null);

  const nw = useCountUp(35598);
  const data = SERIES[range];
  const last = data[data.length - 1].v;
  const delta = (((last - data[0].v) / data[0].v) * 100).toFixed(1);
  const txns = useMemo(() => TXNS.filter((t) => (cat === "all" || t.cat === cat) && (q === "" || t.name.toLowerCase().includes(q.toLowerCase()))), [cat, q]);

  return (
    <div
      ref={wrapRef}
      onPointerMove={(e) => { const r = wrapRef.current!.getBoundingClientRect(); gx.set(((e.clientX - r.left) / r.width) * 100); gy.set(((e.clientY - r.top) / r.height) * 100); }}
      style={{ position: "relative", minHeight: "100vh", background: "hsl(var(--background))", color: "hsl(var(--foreground))", fontFamily: "'Instrument Sans',system-ui,sans-serif", overflow: "hidden" }}
    >
      {/* light/dark toggle — Ledger Paper ⇄ Midnight (the real shipped themes) */}
      <button onClick={() => setDark((d) => !d)} style={{ position: "fixed", top: 12, right: 12, zIndex: 50, fontFamily: "'Spline Sans Mono',monospace", fontSize: ".68rem", padding: ".35rem .7rem", borderRadius: 6, border: "1px solid hsl(var(--rule-strong)/.4)", background: "hsl(var(--card))", color: "hsl(var(--foreground))", cursor: "pointer" }}>
        ◐ {dark ? "Midnight" : "Ledger Paper"}
      </button>
      {/* REACTIVE BACKGROUND: faint flowing guilloché + cursor glow + hover-tint */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0, opacity: 0.5 }}><GuillocheGL opacity={0.16} /></div>
      <motion.div aria-hidden style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none", background: bgGlow }} />
      <AnimatePresence>
        {hovered && (
          <motion.div key={hovered} aria-hidden initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none", background: "radial-gradient(800px circle at 50% 30%, hsl(var(--primary) / 0.06), transparent 65%)" }} />
        )}
      </AnimatePresence>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1180, margin: "0 auto", padding: "2rem clamp(1rem,4vw,3rem) 6rem" }}>
        {/* top bar */}
        <header style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginBottom: "1.6rem" }}>
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            <p className="dept-label">Department of Personal Accounts</p>
            <h1 className="font-display" style={{ fontSize: "1.8rem", fontWeight: 600 }}>Good evening, Advik</h1>
          </motion.div>
          <div style={{ marginLeft: "auto", display: "flex", gap: ".6rem", alignItems: "center" }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search transactions…"
              style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".82rem", padding: ".5rem .8rem", background: "hsl(var(--card))", border: "1px solid hsl(var(--rule-strong)/.4)", color: "hsl(var(--foreground))", outline: "none", minWidth: 200 }} />
            <motion.button whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }} style={btn(true)}>+ Add</motion.button>
          </div>
        </header>

        {/* tabs */}
        <div style={{ display: "flex", gap: "1.4rem", borderBottom: "1px solid hsl(var(--rule))", marginBottom: "1.6rem" }}>
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)} style={{ position: "relative", background: "none", border: "none", cursor: "pointer", padding: ".5rem 0", fontSize: ".9rem", fontWeight: tab === t ? 600 : 400, color: tab === t ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))" }}>
              {t}
              {tab === t && <motion.div layoutId="tab-underline" style={{ position: "absolute", left: 0, right: 0, bottom: -1, height: 2, background: "hsl(var(--gold))" }} />}
            </button>
          ))}
        </div>

        {/* KPI row — each pops on hover */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: "1rem", marginBottom: "1.4rem" }}>
          {[
            { id: "nw", l: "Net Worth", v: `$${nw.toLocaleString()}`, d: "+2.4%" },
            { id: "s2s", l: "Safe to Spend", v: "$612.40", d: "11 days" },
            { id: "risk", l: "Overdraft Risk", v: "27%", d: "low" },
            { id: "month", l: "This Month", v: "−$1,574", d: "vs −$1,720" },
          ].map((k, i) => (
            <motion.div key={k.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
              <PopCard onHoverChange={(h) => setHovered(h ? k.id : null)} style={{ padding: "1rem 1.1rem" }}>
                <p className="dept-label">{k.l}</p>
                <p className="intaglio figure" style={{ fontSize: "1.7rem", marginTop: ".25rem" }}>{k.v}</p>
                <p style={{ fontSize: ".75rem", color: "hsl(var(--credit))", marginTop: ".15rem", fontFamily: "'Spline Sans Mono',monospace" }}>{k.d}</p>
              </PopCard>
            </motion.div>
          ))}
        </div>

        {/* chart card */}
        <PopCard style={{ padding: "1.3rem 1.4rem", marginBottom: "1.4rem" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "1rem", flexWrap: "wrap", marginBottom: ".8rem" }}>
            <div>
              <p className="dept-label">Balance trend</p>
              <p className="intaglio figure" style={{ fontSize: "2.2rem" }}>${last.toLocaleString()}</p>
            </div>
            <span style={{ color: "hsl(var(--credit))", fontFamily: "'Spline Sans Mono',monospace", fontSize: ".85rem" }}>▲ {delta}%</span>
            <div style={{ marginLeft: "auto", display: "flex", border: "1px solid hsl(var(--rule-strong)/.35)" }}>
              {RANGES.map((r) => (
                <button key={r} onClick={() => setRange(r)} style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".75rem", padding: ".35rem .7rem", border: "none", cursor: "pointer", background: range === r ? "hsl(var(--gold)/.85)" : "transparent", color: range === r ? "hsl(167 30% 10%)" : "hsl(var(--muted-foreground))", transition: "background .2s" }}>{r}</button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={data} margin={{ left: 4, right: 8, top: 6, bottom: 0 }}>
              <defs><linearGradient id="wsFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={ink("--chart-3")} stopOpacity={0.3} /><stop offset="100%" stopColor={ink("--chart-3")} stopOpacity={0} /></linearGradient></defs>
              <CartesianGrid stroke={ink("--rule", 0.5)} strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="d" tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }} axisLine={false} tickLine={false} minTickGap={28} />
              <YAxis tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(1)}k`} axisLine={false} tickLine={false} width={48} />
              <Tooltip contentStyle={tooltipStyle()} formatter={(v: number) => [`$${v.toLocaleString()}`, "Balance"]} cursor={{ stroke: ink("--gold"), strokeWidth: 1, strokeDasharray: "4 4" }} />
              <ReferenceLine y={0} stroke={ink("--debit", 0.5)} />
              <Area type="monotone" dataKey="v" stroke={ink("--chart-3")} strokeWidth={2} fill="url(#wsFill)" dot={false} activeDot={{ r: 5, fill: ink("--gold") }} animationDuration={500} />
            </AreaChart>
          </ResponsiveContainer>
        </PopCard>

        {/* budgets + transactions */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: "1.4rem", alignItems: "start" }}>
          <PopCard style={{ padding: "1.2rem 1.3rem" }}>
            <p className="dept-label" style={{ marginBottom: ".9rem" }}>Budget envelopes</p>
            {BUDGETS.map((b) => {
              const pct = Math.min(1, b.used / b.limit); const over = pct > 0.9;
              return (
                <div key={b.cat} style={{ marginBottom: "1rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: ".82rem", marginBottom: ".3rem" }}>
                    <span>{b.cat}</span>
                    <span className="figure" style={{ fontFamily: "'Spline Sans Mono',monospace", color: over ? "hsl(var(--debit))" : "hsl(var(--muted-foreground))" }}>${b.used} / ${b.limit}</span>
                  </div>
                  <div style={{ height: 8, background: "hsl(var(--rule-strong)/.18)", position: "relative", overflow: "hidden" }} title={`${Math.round(pct * 100)}% used · $${b.limit - b.used} left`}>
                    <motion.div initial={{ scaleX: 0 }} whileInView={{ scaleX: pct }} viewport={{ once: true }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} style={{ transformOrigin: "left", position: "absolute", inset: 0, background: over ? "hsl(var(--debit))" : "hsl(var(--gold))" }} />
                  </div>
                </div>
              );
            })}
          </PopCard>

          <PopCard style={{ padding: "1.2rem 1.3rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: ".8rem", flexWrap: "wrap", gap: ".5rem" }}>
              <p className="dept-label">Recent ledger</p>
              <div style={{ display: "flex", gap: ".35rem", flexWrap: "wrap" }}>
                {CATS.map((c) => (
                  <motion.button key={c.key} whileHover={{ scale: 1.06 }} whileTap={{ scale: 0.95 }} onClick={() => setCat(c.key)}
                    style={{ fontSize: ".66rem", fontFamily: "'Spline Sans Mono',monospace", letterSpacing: ".04em", textTransform: "uppercase", padding: ".22rem .5rem", border: `1px solid ${cat === c.key ? "hsl(var(--gold))" : "hsl(var(--rule-strong)/.3)"}`, background: cat === c.key ? "hsl(var(--gold)/.14)" : "transparent", color: "hsl(var(--foreground))", cursor: "pointer" }}>{c.label}</motion.button>
                ))}
              </div>
            </div>
            <motion.div layout>
              <AnimatePresence initial={false}>
                {txns.map((t) => (
                  <motion.div key={t.id} layout initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.25 }} style={{ borderBottom: "1px solid hsl(var(--rule))", overflow: "hidden" }}>
                    <motion.button whileHover={{ x: 4 }} onClick={() => setExpanded(expanded === t.id ? null : t.id)} style={{ width: "100%", display: "grid", gridTemplateColumns: "auto 1fr auto", gap: ".8rem", alignItems: "center", padding: ".6rem 0", background: "none", border: "none", cursor: "pointer", textAlign: "left", color: "inherit", fontFamily: "'Spline Sans Mono',monospace", fontSize: ".84rem" }}>
                      <span style={{ color: "hsl(var(--muted-foreground))" }}>{t.date}</span>
                      <span>{t.name}</span>
                      <span className="figure" style={{ color: t.amt < 0 ? "hsl(var(--debit))" : "hsl(var(--credit))" }}>{t.amt < 0 ? "−" : "+"}${Math.abs(t.amt).toFixed(2)}</span>
                    </motion.button>
                    <AnimatePresence>
                      {expanded === t.id && (
                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }} style={{ overflow: "hidden" }}>
                          <p style={{ fontSize: ".78rem", color: "hsl(var(--muted-foreground))", padding: "0 0 .7rem .1rem" }}>{t.note}</p>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                ))}
              </AnimatePresence>
            </motion.div>
            {txns.length === 0 && <p style={{ fontSize: ".82rem", color: "hsl(var(--muted-foreground))", fontStyle: "italic", padding: ".6rem 0" }}>No matching transactions.</p>}
          </PopCard>
        </div>
      </div>
    </div>
  );

  function btn(primary: boolean): React.CSSProperties {
    return { fontFamily: "'Instrument Sans',sans-serif", fontSize: ".82rem", fontWeight: 600, padding: ".5rem 1rem", border: primary ? "none" : "1px solid hsl(var(--rule-strong)/.4)", background: primary ? "hsl(var(--primary))" : "transparent", color: primary ? "hsl(46 52% 96%)" : "hsl(var(--foreground))", cursor: "pointer" };
  }
}
