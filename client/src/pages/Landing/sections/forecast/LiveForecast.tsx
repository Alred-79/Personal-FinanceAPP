import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { BASE_BURN, DAYS, simulate, smoothPath, type SimResult } from "./sim";

const W = 660;
const H = 300;
const PADL = 46;
const PADR = 22;
const PADT = 22;
const PADB = 30;
const BAL_MIN = -1300;
const BAL_MAX = 3100;

const xFor = (day: number) => PADL + (day / (DAYS - 1)) * (W - PADL - PADR);
const yFor = (bal: number) =>
  PADT + (1 - (bal - BAL_MIN) / (BAL_MAX - BAL_MIN)) * (H - PADT - PADB);

// Reveal-on-interact scales (see docs plan): a balance $ axis in the left gutter
// and a spending gauge in the right margin, both shown on hover / drag.
const BURN_MIN = 6;
const BURN_MAX = 150;
// Balance-axis ticks — fixed range, so a hardcoded set beats a niceTicks() helper.
// Coarse on hover; the fine half-steps fade in only while actively dragging (the
// chart is magnified then, so the extra labels stay legible).
const TICKS_COARSE = [3000, 2000, 1000, 0, -1000];
const TICKS_FINE = [2500, 1500, 500, -500];
const tickLabel = (t: number) =>
  t === 0 ? "$0" : `${t < 0 ? "−" : ""}$${Math.abs(t) / 1000}k`; // real minus −
// Spending gauge rail in the right margin. Heavy spend at the BOTTOM, lean at the
// TOP, so the knob tracks the drag gesture: drag down → more spend → knob sinks,
// exactly like the band sinks. (Drag up → leaner → knob + band rise together.)
const GX = W - PADR + 6; // 644
const GY_TOP = PADT; // 22  → leanest spend (BURN_MIN)
const GY_BOT = H - PADB; // 270 → heaviest spend (BURN_MAX)
const gaugeY = (b: number) =>
  GY_TOP + ((b - BURN_MIN) / (BURN_MAX - BURN_MIN)) * (GY_BOT - GY_TOP);

/** The what-if levers — each layers extra net flows onto the baseline schedule. */
const SCENARIOS: { key: string; label: string; tone: "credit" | "debit"; net: Record<number, number> }[] = [
  { key: "gig", label: "+ $840 extra income", tone: "credit", net: { 10: 420, 24: 420 } },
  { key: "bill", label: "Cancel a $130 bill", tone: "credit", net: { 12: 130 } },
  { key: "buy", label: "Buy something −$600", tone: "debit", net: { 16: -600 } },
];

function netFromChips(active: Set<string>): number[] {
  const arr = new Array(DAYS).fill(0);
  for (const s of SCENARIOS) {
    if (!active.has(s.key)) continue;
    for (const [d, amt] of Object.entries(s.net)) arr[Number(d)] += amt;
  }
  return arr;
}

const dollars = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(Math.round(n)).toLocaleString()}`;

/** Build the smooth filled band (p5..p95 corridor) for a sim result. */
function bandPath(r: SimResult): string {
  const high: [number, number][] = r.high.map((b, d) => [xFor(d), yFor(b)]);
  const low: [number, number][] = r.low.map((b, d) => [xFor(d), yFor(b)]);
  const top = smoothPath(high);
  const bottom = smoothPath(low.slice().reverse()).replace(/^M/, "L");
  return `${top} ${bottom} Z`;
}
const linePath = (r: SimResult) => smoothPath(r.med.map((b, d) => [xFor(d), yFor(b)]));

/**
 * The live Sea-Chart — a faithful, in-browser slice of the real forecast engine.
 * Drag to model heavier or lighter spending and the whole probability cloud
 * (the simulated 5th–95th percentile band) re-simulates, with the overdraft probability
 * re-sounding. Toggle a what-if and a scenario line overlays the baseline.
 */
export function LiveForecast() {
  const reduce = useReducedMotion();
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef({ active: false, lastY: 0 });
  const [burn, setBurn] = useState(BASE_BURN);
  const [chips, setChips] = useState<Set<string>>(new Set());
  const [dragged, setDragged] = useState(false);
  // hovered = desktop discoverability; active = currently dragging (also fires on
  // mobile touch where hover doesn't exist). reveal drives the scale overlays.
  const [active, setActive] = useState(false);
  const [hovered, setHovered] = useState(false);
  const reveal = hovered || active;

  const base = useMemo(() => simulate({ burn }), [burn]);
  const scenarioNet = useMemo(() => netFromChips(chips), [chips]);
  const hasScenario = chips.size > 0;
  const scenario = useMemo(
    () => (hasScenario ? simulate({ burn, scenarioNet }) : null),
    [burn, scenarioNet, hasScenario]
  );

  const onDown = (e: ReactPointerEvent) => {
    drag.current.active = true;
    drag.current.lastY = e.clientY;
    setDragged(true);
    setActive(true);
    try {
      (e.target as Element).setPointerCapture?.(e.pointerId);
    } catch {
      /* ignore */
    }
  };
  const onMove = (e: ReactPointerEvent) => {
    if (!drag.current.active) return;
    const dy = e.clientY - drag.current.lastY;
    drag.current.lastY = e.clientY;
    setBurn((b) => Math.max(BURN_MIN, Math.min(BURN_MAX, b + dy * 0.55)));
  };
  const onUp = () => {
    drag.current.active = false;
    setActive(false);
  };

  const toggle = (key: string) =>
    setChips((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const shown = scenario ?? base;
  const hx = xFor(base.troughDay);
  const hy = yFor(base.med[base.troughDay]);
  const runwayOf = (med: number[]) => {
    for (let d = 0; d < med.length; d++) if (med[d] < 0) return d;
    return med.length;
  };
  const runway = runwayOf(base.med);
  const sRunway = scenario ? runwayOf(scenario.med) : runway;
  const dRunway = sRunway - runway;

  const probClass = (p: number) => (p > 0.5 ? "ink-debit" : p > 0.2 ? "text-gold" : "ink-credit");

  return (
    <div
      className="security-window p-5"
      style={{
        // Magnify the whole instrument while dragging so the fine ticks + gauge
        // become readable under the user's finger. Pure transform (no reflow).
        transform: active && !reduce ? "scale(1.05)" : "scale(1)",
        transformOrigin: "center",
        transition: reduce ? "none" : "transform 240ms ease",
        position: "relative",
        zIndex: active ? 5 : undefined,
      }}
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none select-none"
        style={{ cursor: "ns-resize" }}
        role="img"
        aria-label={`Cash-flow forecast you can drag to model spending. Spending ${dollars(
          Math.round(burn * 30)
        )} per month. Overdraft probability ${Math.round(shown.prob * 100)} percent.`}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => {
          setHovered(false);
          onUp();
        }}
      >
        <defs>
          <pattern id="lf-hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <line x1="0" y1="0" x2="0" y2="6" stroke="hsl(var(--gold))" strokeWidth="1" opacity="0.3" />
          </pattern>
        </defs>

        {/* (A) balance $ axis — left gutter ruler, revealed on hover/drag. The $0
            tick lands on the OVERDRAFT line (yFor(0)); fine half-steps join while
            actively dragging (chart enlarged). aria-hidden + pointerEvents none so
            it never steals the drag capture. */}
        <g
          aria-hidden="true"
          pointerEvents="none"
          style={{ opacity: reveal ? 1 : 0, transition: reduce ? "none" : "opacity 220ms ease" }}
        >
          {TICKS_COARSE.map((t) => (
            <g key={`tc${t}`}>
              <line x1={PADL - 3} x2={PADL} y1={yFor(t)} y2={yFor(t)} stroke="hsl(var(--muted-foreground))" strokeWidth={1} opacity={0.5} />
              <text x={PADL - 8} y={yFor(t)} textAnchor="end" dominantBaseline="middle" className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="8.5" letterSpacing="0.04em" fill="hsl(var(--muted-foreground))">
                {tickLabel(t)}
              </text>
            </g>
          ))}
          <g style={{ opacity: active ? 1 : 0, transition: reduce ? "none" : "opacity 200ms ease" }}>
            {TICKS_FINE.map((t) => (
              <g key={`tf${t}`}>
                <line x1={PADL - 2} x2={PADL} y1={yFor(t)} y2={yFor(t)} stroke="hsl(var(--muted-foreground))" strokeWidth={1} opacity={0.4} />
                <text x={PADL - 8} y={yFor(t)} textAnchor="end" dominantBaseline="middle" className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="8" letterSpacing="0.04em" fill="hsl(var(--muted-foreground))" opacity={0.85}>
                  {tickLabel(t)}
                </text>
              </g>
            ))}
          </g>
        </g>

        {/* zero / overdraft threshold */}
        <line x1={PADL} x2={W - PADR} y1={yFor(0)} y2={yFor(0)} stroke="hsl(var(--debit))" strokeWidth={1} strokeDasharray="4 5" opacity={0.6} />
        <text x={W - PADR} y={yFor(0) - 6} textAnchor="end" className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="10" letterSpacing="0.12em" fill="hsl(var(--debit))">
          OVERDRAFT
        </text>

        {/* baseline simulated band + median — a soft gold tint so the 5th–95th
            percentile corridor reads at a glance, the engraved hatch on top */}
        <path d={bandPath(base)} fill="hsl(var(--gold) / 0.1)" stroke="none" opacity={hasScenario ? 0.55 : 1} />
        <path d={bandPath(base)} fill="url(#lf-hatch)" stroke="hsl(var(--gold) / 0.5)" strokeWidth={1.3} strokeDasharray="3 3" opacity={hasScenario ? 0.6 : 1} />
        <path d={linePath(base)} fill="none" stroke="hsl(var(--credit))" strokeWidth={2.6} strokeLinecap="round" opacity={hasScenario ? 0.5 : 1} />

        {/* scenario overlay */}
        {scenario && (
          <>
            <path d={bandPath(scenario)} fill="hsl(var(--gold) / 0.08)" stroke="hsl(var(--gold) / 0.3)" strokeWidth={1} />
            <path d={linePath(scenario)} fill="none" stroke="hsl(var(--gold))" strokeWidth={2.6} strokeDasharray="6 4" strokeLinecap="round" />
          </>
        )}

        {/* regime-shift annotation */}
        <line x1={xFor(6)} x2={xFor(6)} y1={PADT} y2={H - PADB} stroke="hsl(var(--gold))" strokeWidth={1} strokeDasharray="2 4" opacity={0.4} />
        <text x={xFor(6) + 5} y={PADT + 11} className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="9.5" letterSpacing="0.08em" fill="hsl(var(--gold))" opacity={0.85}>
          ↑ recent spending +$465/mo · included
        </text>

        {/* lowest-point marker on the median */}
        <circle cx={hx} cy={hy} r={5} fill={base.med[base.troughDay] < 0 ? "hsl(var(--debit))" : "hsl(var(--gold))"} stroke="hsl(var(--background))" strokeWidth={2} />

        {/* spend handle at the trough — the chart's visible grab point. The
            whole chart is draggable (ns-resize), so this is an affordance, not
            the only hit target. */}
        <g style={{ cursor: "ns-resize" }}>
          <circle cx={hx} cy={hy} r={17} fill="transparent" />
          {!reduce && (
            <circle cx={hx} cy={hy} r={6} fill="none" stroke="hsl(var(--gold))" opacity={0.5}>
              <animate attributeName="r" values="6;16;6" dur="2.4s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.5;0;0.5" dur="2.4s" repeatCount="indefinite" />
            </circle>
          )}
        </g>

        {/* (B) spending gauge — fixed rail in the right margin, revealed on
            hover/drag. The knob + colored delta travel along it as you drag, so
            its position quantifies "what up/down does"; the $/mo readout shows
            only while actively dragging. aria-hidden + pointerEvents none. */}
        <g
          aria-hidden="true"
          pointerEvents="none"
          style={{ opacity: reveal ? 1 : 0, transition: reduce ? "none" : "opacity 220ms ease" }}
        >
          <line x1={GX} x2={GX} y1={GY_TOP} y2={GY_BOT} stroke="hsl(var(--gold) / 0.25)" strokeWidth={1} />
          {/* baseline reference tick (the "vs base" readout names it; no label
              here — a right-side word would clip the viewBox edge) */}
          <line x1={GX - 4} x2={GX + 4} y1={gaugeY(BASE_BURN)} y2={gaugeY(BASE_BURN)} stroke="hsl(var(--muted-foreground))" strokeWidth={1} opacity={0.7} />
          {/* colored delta segment: baseline → current spend */}
          <line
            x1={GX}
            x2={GX}
            y1={gaugeY(BASE_BURN)}
            y2={gaugeY(burn)}
            stroke={burn > BASE_BURN ? "hsl(var(--debit))" : "hsl(var(--credit))"}
            strokeWidth={3}
            strokeLinecap="round"
          />
          {/* lean (top) / heavy (bottom) endpoints — match the drag gesture */}
          <text x={GX - 6} y={GY_TOP + 7} textAnchor="end" dominantBaseline="middle" className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="8" fill="hsl(var(--muted-foreground))">
            lean
          </text>
          <text x={GX - 6} y={GY_BOT - 5} textAnchor="end" dominantBaseline="middle" className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="8" fill="hsl(var(--muted-foreground))">
            heavy
          </text>
          {/* live knob */}
          <circle cx={GX} cy={gaugeY(burn)} r={4} fill="hsl(var(--gold))" stroke="hsl(var(--background))" strokeWidth={1} />
          {/* live readout — only while actively dragging, left of the rail so it
              never clips the viewBox edge; a faint backing keeps it legible. */}
          <g style={{ opacity: active ? 1 : 0, transition: reduce ? "none" : "opacity 180ms ease" }}>
            <rect x={GX - 12 - 80} y={gaugeY(burn) - 13} width={80} height={24} rx={3} fill="hsl(var(--card) / 0.88)" stroke="hsl(var(--rule-strong) / 0.35)" strokeWidth={0.5} />
            <text x={GX - 16} y={gaugeY(burn) - 2} textAnchor="end" className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="9" fontWeight={600} fill="hsl(var(--foreground))">
              {dollars(Math.round(burn * 30))}/mo
            </text>
            {Math.round((burn - BASE_BURN) * 30) !== 0 && (
              <text
                x={GX - 16}
                y={gaugeY(burn) + 8}
                textAnchor="end"
                className="figure"
                fontFamily="'Spline Sans Mono', monospace"
                fontSize="7.5"
                fill={burn > BASE_BURN ? "hsl(var(--debit))" : "hsl(var(--credit))"}
              >
                {`${burn > BASE_BURN ? "+" : "−"}${dollars(Math.abs(Math.round((burn - BASE_BURN) * 30)))} vs base`}
              </text>
            )}
          </g>
        </g>

        {/* first-run drag hint: a bobbing tag that retires once you've dragged */}
        {!dragged && (
          <g transform={`translate(${hx}, ${hy - 36})`} pointerEvents="none">
            <g>
              <rect x={-35} y={-12} width={70} height={21} rx={10.5} fill="hsl(var(--gold))" />
              <text
                x={0}
                y={1}
                textAnchor="middle"
                dominantBaseline="middle"
                fontFamily="'Spline Sans Mono', monospace"
                fontSize="9.5"
                fontWeight={600}
                letterSpacing="0.14em"
                fill="hsl(var(--background))"
              >
                DRAG ↕
              </text>
              {!reduce && (
                <animateTransform
                  attributeName="transform"
                  type="translate"
                  values="0 0; 0 -4; 0 0"
                  dur="1.9s"
                  repeatCount="indefinite"
                />
              )}
            </g>
            {/* little spur pointing down at the handle */}
            <path d="M0 13 l-4.5 -6 h9 Z" fill="hsl(var(--gold))" />
          </g>
        )}
      </svg>

      {/* what-if chips */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="dept-label mr-1">What if</span>
        {SCENARIOS.map((s) => {
          const on = chips.has(s.key);
          return (
            <button
              key={s.key}
              onClick={() => toggle(s.key)}
              className={cn(
                "press border px-3 py-1.5 text-[0.74rem] font-semibold uppercase tracking-[0.04em] transition-colors",
                on
                  ? "border-gold/70 bg-gold/10 text-foreground"
                  : "border-rule-strong/50 text-muted-foreground hover:text-foreground"
              )}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      {/* live metrics */}
      <div className="mt-4 grid grid-cols-3 gap-px border border-rule-strong/30 bg-rule-strong/25">
        <div className="bg-card px-4 py-3">
          <div className="dept-label">Chance below $0</div>
          <div className={cn("figure mt-1 text-[1.12rem]", probClass(shown.prob))}>
            {Math.round(shown.prob * 100)}%
            {scenario && (
              <span className="ml-1.5 text-[0.74rem] text-muted-foreground">from {Math.round(base.prob * 100)}%</span>
            )}
          </div>
        </div>
        <div className="bg-card px-4 py-3">
          <div className="dept-label">Modeled low · 5th–95th simulated range</div>
          <div className={cn("figure mt-1 text-[1.12rem]", shown.troughMed < 0 ? "ink-debit" : "ink-credit")}>
            {dollars(shown.troughMed)}
          </div>
          <div className="figure mt-0.5 text-[0.72rem] text-muted-foreground">
            {dollars(shown.troughLow)} … {dollars(shown.troughHigh)}
          </div>
        </div>
        <div className="bg-card px-4 py-3">
          <div className="dept-label">Runway without a shortfall</div>
          <div className={cn("figure mt-1 text-[1.12rem]", sRunway >= DAYS ? "ink-credit" : "ink-debit")}>
            {sRunway >= DAYS ? "all 30 days" : `${sRunway} days`}
          </div>
          {scenario && dRunway !== 0 && (
            <div className={cn("figure mt-0.5 text-[0.72rem]", dRunway > 0 ? "ink-credit" : "ink-debit")}>
              {dRunway > 0 ? "+" : ""}
              {dRunway} days
            </div>
          )}
        </div>
      </div>

      <p className="mt-3 flex items-center justify-center gap-1.5 text-center text-[0.78rem] text-muted-foreground">
        <span aria-hidden className="text-gold">↕</span>
        Drag up or down to change spending · 240 modeled futures update live
      </p>
    </div>
  );
}
