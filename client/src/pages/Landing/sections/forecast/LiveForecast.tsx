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

/** The what-if levers — each layers extra net flows onto the baseline schedule. */
const SCENARIOS: { key: string; label: string; tone: "credit" | "debit"; net: Record<number, number> }[] = [
  { key: "gig", label: "+ Side gig", tone: "credit", net: { 10: 420, 24: 420 } },
  { key: "bill", label: "Kill a $130 bill", tone: "credit", net: { 12: 130 } },
  { key: "buy", label: "Big purchase −$600", tone: "debit", net: { 16: -600 } },
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
 * (a calibrated ~90% trough band) re-simulates, with the overdraft probability
 * re-sounding. Toggle a what-if and a scenario line overlays the baseline.
 */
export function LiveForecast() {
  const reduce = useReducedMotion();
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef({ active: false, lastY: 0 });
  const [burn, setBurn] = useState(BASE_BURN);
  const [chips, setChips] = useState<Set<string>>(new Set());
  const [dragged, setDragged] = useState(false);

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
    setBurn((b) => Math.max(6, Math.min(150, b + dy * 0.55)));
  };
  const onUp = () => {
    drag.current.active = false;
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
    <div className="security-window p-5">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none select-none"
        style={{ cursor: "ns-resize" }}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
      >
        <defs>
          <pattern id="lf-hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <line x1="0" y1="0" x2="0" y2="6" stroke="hsl(var(--gold))" strokeWidth="1" opacity="0.3" />
          </pattern>
        </defs>

        {/* zero / overdraft threshold */}
        <line x1={PADL} x2={W - PADR} y1={yFor(0)} y2={yFor(0)} stroke="hsl(var(--debit))" strokeWidth={1} strokeDasharray="4 5" opacity={0.6} />
        <text x={W - PADR} y={yFor(0) - 6} textAnchor="end" className="figure" fontFamily="'Spline Sans Mono', monospace" fontSize="10" letterSpacing="0.12em" fill="hsl(var(--debit))">
          OVERDRAFT
        </text>

        {/* baseline calibrated band + median — a soft gold tint so the ~90%
            trough corridor reads at a glance, the engraved hatch on top */}
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
          ↑ spending +$465/mo · folded in
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
          <div className="dept-label">Overdraft probability</div>
          <div className={cn("figure mt-1 text-[1.12rem]", probClass(shown.prob))}>
            {Math.round(shown.prob * 100)}%
            {scenario && (
              <span className="ml-1.5 text-[0.74rem] text-muted-foreground">from {Math.round(base.prob * 100)}%</span>
            )}
          </div>
        </div>
        <div className="bg-card px-4 py-3">
          <div className="dept-label">Projected low · 90% band</div>
          <div className={cn("figure mt-1 text-[1.12rem]", shown.troughMed < 0 ? "ink-debit" : "ink-credit")}>
            {dollars(shown.troughMed)}
          </div>
          <div className="figure mt-0.5 text-[0.72rem] text-muted-foreground">
            {dollars(shown.troughLow)} … {dollars(shown.troughHigh)}
          </div>
        </div>
        <div className="bg-card px-4 py-3">
          <div className="dept-label">Runway · stays solvent</div>
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
        Drag the chart up or down to model spending · 240 simulated futures, re-run live
      </p>
    </div>
  );
}
