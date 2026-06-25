import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { Rise } from "../shared";

const W = 620;
const H = 260;
const PAD = 26;
const DAYS = 24;
const START = 2400;
const END = 2150;
const TROUGH_DAY = 14;
const BAL_MIN = -600;
const BAL_MAX = 3200;

const xFor = (day: number) => PAD + (day / (DAYS - 1)) * (W - PAD * 2);
const yFor = (bal: number) =>
  PAD + (1 - (bal - BAL_MIN) / (BAL_MAX - BAL_MIN)) * (H - PAD * 2);

/** A smooth cubic curve start → draggable trough → recovery. */
function linePath(low: number) {
  const p0 = [xFor(0), yFor(START)];
  const pt = [xFor(TROUGH_DAY), yFor(low)];
  const pe = [xFor(DAYS - 1), yFor(END)];
  const m1 = (p0[0] + pt[0]) / 2;
  const m2 = (pt[0] + pe[0]) / 2;
  return `M ${p0[0]} ${p0[1]} C ${m1} ${p0[1]} ${m1} ${pt[1]} ${pt[0]} ${pt[1]} C ${m2} ${pt[1]} ${m2} ${pe[1]} ${pe[0]} ${pe[1]}`;
}

/** Overdraft probability — a smooth sigmoid that climbs as the low nears zero. */
function overdraftProb(low: number) {
  return Math.round((1 / (1 + Math.exp(low / 240))) * 100);
}

/**
 * The live Sea-Chart — the product's signature interaction, on the landing. Drag
 * the trough to model spending more or less and watch the projected low and the
 * overdraft probability re-sound. Money figures stay sober (.figure, colour law).
 */
export function SeaChartLive() {
  const reduce = useReducedMotion();
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);
  const [low, setLow] = useState(820);

  const setFromClientY = (clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const r = svg.getBoundingClientRect();
    const yUnits = ((clientY - r.top) / r.height) * H;
    const bal = BAL_MIN + (1 - (yUnits - PAD) / (H - PAD * 2)) * (BAL_MAX - BAL_MIN);
    setLow(Math.max(-550, Math.min(2300, Math.round(bal / 10) * 10)));
  };

  const onDown = (e: ReactPointerEvent) => {
    dragging.current = true;
    try {
      (e.target as Element).setPointerCapture?.(e.pointerId);
    } catch {
      /* no active pointer to capture — ignore */
    }
    setFromClientY(e.clientY);
  };
  const onMove = (e: ReactPointerEvent) => {
    if (dragging.current) setFromClientY(e.clientY);
  };
  const onUp = () => {
    dragging.current = false;
  };

  const path = linePath(low);
  const area = `${path} L ${xFor(DAYS - 1)} ${yFor(BAL_MIN)} L ${xFor(0)} ${yFor(BAL_MIN)} Z`;
  const prob = overdraftProb(low);
  const tx = xFor(TROUGH_DAY);
  const ty = yFor(low);

  return (
    <section className="mt-28">
      <Rise className="mx-auto max-w-[42rem] text-center">
        <p className="dept-label">The Sea-Chart · live</p>
        <h2 className="mt-2 font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.6rem)" }}>
          Drag the line. Hear it re-sound.
        </h2>
        <p className="mt-3 text-[1.02rem] text-muted-foreground">
          Pull your projected low up or down and watch the overdraft probability
          answer — a forecast you can argue with, not a flat guess.
        </p>
      </Rise>

      <Rise className="mx-auto mt-8 max-w-[760px]" delay={0.1}>
        <div className="security-window p-5">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="w-full touch-none select-none"
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
          >
            {/* overdraft threshold */}
            <line
              x1={PAD}
              x2={W - PAD}
              y1={yFor(0)}
              y2={yFor(0)}
              stroke="hsl(var(--debit))"
              strokeWidth={1}
              strokeDasharray="4 5"
              opacity={0.6}
            />
            <text
              x={W - PAD}
              y={yFor(0) - 7}
              textAnchor="end"
              className="figure"
              fontFamily="'Spline Sans Mono', monospace"
              fontSize="10"
              letterSpacing="0.12em"
              fill="hsl(var(--debit))"
            >
              OVERDRAFT
            </text>

            <path d={area} fill="hsl(var(--credit) / 0.13)" />
            <path d={path} fill="none" stroke="hsl(var(--credit))" strokeWidth={2.5} strokeLinecap="round" />

            {/* draggable trough handle */}
            <g onPointerDown={onDown} style={{ cursor: "grab" }}>
              <circle cx={tx} cy={ty} r={16} fill="transparent" />
              {!reduce && (
                <circle cx={tx} cy={ty} r={6} fill="none" stroke="hsl(var(--gold))" opacity={0.5}>
                  <animate attributeName="r" values="6;15;6" dur="2.4s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0.5;0;0.5" dur="2.4s" repeatCount="indefinite" />
                </circle>
              )}
              <circle cx={tx} cy={ty} r={6.5} fill="hsl(var(--gold))" stroke="hsl(var(--background))" strokeWidth={2} />
            </g>
          </svg>

          <div className="mt-4 grid grid-cols-2 gap-px border border-rule-strong/30 bg-rule-strong/25">
            <div className="bg-card px-4 py-3">
              <div className="dept-label">Projected low</div>
              <div className={cn("figure mt-1 text-[1.12rem]", low < 0 ? "ink-debit" : "ink-credit")}>
                {low < 0 ? "-" : ""}${Math.abs(low).toLocaleString()}
              </div>
            </div>
            <div className="bg-card px-4 py-3">
              <div className="dept-label">Overdraft probability</div>
              <div
                className={cn(
                  "figure mt-1 text-[1.12rem]",
                  prob > 50 ? "ink-debit" : prob > 20 ? "text-gold" : "ink-credit"
                )}
              >
                {prob}%
              </div>
            </div>
          </div>
        </div>
      </Rise>
    </section>
  );
}
