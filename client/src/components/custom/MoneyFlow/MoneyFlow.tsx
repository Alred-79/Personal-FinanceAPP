import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { EmptyState } from "@/components/engraving/EmptyState";
import { Guilloche, GuillocheBand } from "@/components/engraving/Guilloche";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  buildFlow,
  ribbonPath,
  centrePath,
  type FlowKind,
  type FlowLayout,
  type FlowNode,
} from "@/lib/flow";

interface SpendingResponse {
  totals_by_category: Record<string, number>;
}

const HEIGHT = 460;
const WINDOWS = [
  { label: "Last 30 days", value: 30 },
  { label: "Last 90 days", value: 90 },
  { label: "Last 12 months", value: 365 },
];

/**
 * Resolve a CSS custom property to rgb for the canvas motes (canvas can't read
 * CSS vars). hsl(triplet) → #rrggbb via a throwaway canvas.
 */
function readVarRGB(name: string): [number, number, number] {
  if (typeof document === "undefined") return [212, 175, 55];
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return [212, 175, 55];
  const triplet = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  ctx.fillStyle = triplet ? `hsl(${triplet})` : "#d4af37";
  const hex = ctx.fillStyle as string; // normalised to #rrggbb
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) return [212, 175, 55];
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
}

/**
 * Per-kind ribbon ink as a CSS-var string, so the SVG re-inks automatically on
 * a light/dark theme flip with no JS — income/saved read as credit/gold,
 * spending as the chart ink, an over-spend as debit.
 */
function kindColor(kind: FlowKind): string {
  switch (kind) {
    case "income":
      return "hsl(var(--credit))";
    case "saved":
      return "hsl(var(--gold))";
    case "reserves":
      return "hsl(var(--debit))";
    case "spending":
      return "hsl(var(--chart-3))";
    default:
      return "hsl(var(--rule-strong))";
  }
}

interface Particle {
  link: number;
  t: number;
  speed: number;
  size: number;
}

/**
 * The Watercourse — a living money-flow Sankey. Every income source pours into
 * the Treasury hub; the hub drains out to spending categories and whatever is
 * set aside. Ribbon thickness is the amount; gold motes stream along each
 * channel at a density set by its share, so the page literally shows money
 * moving. Hover a gate to trace its channels. Honours reduced-motion (motes
 * freeze) and ships an SR-only table of the same figures.
 */
export default function MoneyFlow() {
  const reduce = useReducedMotion();
  const [isDark, setIsDark] = useState(false);
  const [days, setDays] = useState(90);
  const [income, setIncome] = useState<Record<string, number> | null>(null);
  const [expense, setExpense] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState(false);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pathRefs = useRef<(SVGPathElement | null)[]>([]);
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<string | null>(null);

  // ── Data: two analytics pulls (income + expense) over the window ──
  useEffect(() => {
    let cancelled = false;
    setIncome(null);
    setExpense(null);
    setError(false);
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - days);
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    const params = { start: iso(start), end: iso(end), bucket: "month" };
    Promise.all([
      api.get<SpendingResponse>("/analytics/spending/", {
        params: { ...params, tx_type: "income" },
      }),
      api.get<SpendingResponse>("/analytics/spending/", {
        params: { ...params, tx_type: "expense" },
      }),
    ])
      .then(([inc, exp]) => {
        if (cancelled) return;
        setIncome(inc.data.totals_by_category ?? {});
        setExpense(exp.data.totals_by_category ?? {});
      })
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [days]);

  // ── Responsive width ──
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth || 800);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const layout: FlowLayout | null = useMemo(() => {
    if (!income || !expense) return null;
    return buildFlow({ income, expense }, { width, height: HEIGHT });
  }, [income, expense, width]);

  // Reset the path ref array whenever the link set changes.
  pathRefs.current = useMemo(
    () => new Array(layout?.links.length ?? 0).fill(null),
    [layout]
  );

  // Track the midnight-vault class on <html> so canvas motes re-ink on a theme
  // flip (the SVG ribbons re-ink for free via their CSS-var fills).
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains("dark"));
    sync();
    const mo = new MutationObserver(sync);
    mo.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);

  const linkColors = useMemo(
    () => (layout?.links ?? []).map((l) => kindColor(l.kind)),
    [layout]
  );

  // ── Particle animation ──
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !layout || layout.links.length === 0) return;
    // jsdom (and headless envs without a canvas backend) throw here rather than
    // returning null — treat any failure as "no canvas, skip the motes".
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext("2d");
    } catch {
      return;
    }
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * dpr;
    canvas.height = HEIGHT * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${HEIGHT}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Seed particles per link, count ∝ share (the bigger the flow, the busier).
    const particles: Particle[] = [];
    layout.links.forEach((l, i) => {
      const n = Math.max(2, Math.round(l.share * 46));
      for (let k = 0; k < n; k++) {
        particles.push({
          link: i,
          t: (k / n + i * 0.13) % 1,
          speed: 0.06 + (i % 3) * 0.012, // fraction of the channel per second
          size: 1.1 + (k % 3) * 0.5,
        });
      }
    });

    const [r, g, b] = readVarRGB("--gold");
    let raf = 0;
    let last = 0;
    const lens: number[] = [];

    const draw = (ts: number) => {
      const dt = last ? Math.min((ts - last) / 1000, 0.05) : 0;
      last = ts;
      ctx.clearRect(0, 0, width, HEIGHT);

      // Cache path lengths once per frame.
      for (let i = 0; i < pathRefs.current.length; i++) {
        const p = pathRefs.current[i];
        lens[i] = p ? p.getTotalLength() : 0;
      }

      ctx.lineCap = "round";
      for (const part of particles) {
        const path = pathRefs.current[part.link];
        const len = lens[part.link];
        if (!path || !len) continue;
        if (!reduce) part.t = (part.t + part.speed * dt) % 1;
        const pt = path.getPointAtLength(part.t * len);
        const link = layout.links[part.link];
        const active =
          !hover || link.sourceId === hover || link.targetId === hover;
        // Fade in/out at the ends so motes don't pop at the gates.
        const edge = Math.min(part.t, 1 - part.t) * 6;
        const a = Math.min(1, edge) * (active ? 0.9 : 0.12);
        if (a <= 0.01) continue;
        const rad = part.size * (active ? 1 : 0.8);

        // A short wake trailing the head reads as current, not a loose dot.
        const tailT = Math.max(0, part.t - 0.05);
        const back = path.getPointAtLength(tailT * len);
        const tg = ctx.createLinearGradient(back.x, back.y, pt.x, pt.y);
        tg.addColorStop(0, `rgba(${r},${g},${b},0)`);
        tg.addColorStop(1, `rgba(${r},${g},${b},${a * 0.5})`);
        ctx.strokeStyle = tg;
        ctx.lineWidth = rad * 0.9;
        ctx.beginPath();
        ctx.moveTo(back.x, back.y);
        ctx.lineTo(pt.x, pt.y);
        ctx.stroke();

        // The mote head — a small struck point of gold leaf.
        const grad = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, rad * 2.4);
        grad.addColorStop(0, `rgba(${r},${g},${b},${a})`);
        grad.addColorStop(0.5, `rgba(${r},${g},${b},${a * 0.5})`);
        grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, rad * 2.4, 0, Math.PI * 2);
        ctx.fill();
      }

      if (!reduce) raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [layout, width, reduce, hover, isDark]);

  // ── States ──
  if (error) {
    return (
      <EmptyState
        seed={21}
        eyebrow="Flow · Unavailable"
        title="The watercourse couldn't be charted"
        description="Analytics didn't answer. Try again in a moment."
      />
    );
  }
  if (!layout) {
    return (
      <div className="space-y-4">
        <WindowSelect days={days} setDays={setDays} />
        <p className="font-mono text-sm text-muted-foreground">
          Tracing the watercourse…
        </p>
      </div>
    );
  }
  if (layout.total <= 0) {
    return (
      <div className="space-y-4">
        <WindowSelect days={days} setDays={setDays} />
        <EmptyState
          seed={20}
          eyebrow="Flow · Nothing in motion"
          title="No money has moved yet"
          description="Once income and spending are on the books, this charts the whole watercourse — every source pouring into the treasury and draining back out."
        />
      </div>
    );
  }

  const sources = layout.nodes.filter((n) => n.side === "source");
  const sinks = layout.nodes.filter((n) => n.side === "sink");
  const hub = layout.nodes.find((n) => n.side === "hub")!;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <WindowSelect days={days} setDays={setDays} />
        <dl className="flex gap-6">
          <Readout label="Inflow" value={layout.totalIncome} tone="credit" />
          <Readout label="Outflow" value={layout.totalExpense} tone="debit" />
          <Readout
            label={layout.surplus >= 0 ? "Set aside" : "Drawn down"}
            value={Math.abs(layout.surplus)}
            tone={layout.surplus >= 0 ? "gold" : "debit"}
          />
        </dl>
      </div>

      <div
        ref={wrapRef}
        className="relative overflow-hidden border border-rule-strong/20 bg-card"
        style={{ height: HEIGHT }}
        onMouseLeave={() => setHover(null)}
      >
        {/* Banknote edge strip */}
        <div className="pointer-events-none absolute inset-x-0 top-0 z-0 text-gold/25">
          <GuillocheBand height={14} waves={5} seed={29} />
        </div>

        {/* The Treasury medallion — a guilloché vignette the channels weave
            through, slowly turning like a struck seal. */}
        <div
          className="pointer-events-none absolute z-0 text-gold/[0.16]"
          style={{
            left: hub.x0 + (hub.x1 - hub.x0) / 2,
            top: (hub.y0 + hub.y1) / 2,
            transform: "translate(-50%, -50%)",
          }}
        >
          <Guilloche
            size={Math.round((hub.y1 - hub.y0) * 1.55)}
            rings={6}
            seed={47}
            animate={!reduce}
            strokeWidth={0.5}
          />
        </div>

        <svg
          width={width}
          height={HEIGHT}
          className="absolute inset-0 z-[1]"
          role="presentation"
        >
          {/* Ribbons (channels), inked in one after another on first paint. */}
          <g>
            {layout.links.map((l, i) => {
              const active =
                !hover || l.sourceId === hover || l.targetId === hover;
              return (
                <path
                  key={l.id}
                  data-ribbon
                  d={ribbonPath(l)}
                  fill={linkColors[i]}
                  fillOpacity={active ? 0.26 : 0.06}
                  stroke={linkColors[i]}
                  strokeOpacity={active ? 0.42 : 0.08}
                  strokeWidth={0.6}
                  className="animate-ink-in"
                  style={{
                    transition: "fill-opacity 220ms, stroke-opacity 220ms",
                    animationDelay: `${i * 55}ms`,
                  }}
                />
              );
            })}
          </g>
          {/* Hidden centre-lines sampled by the particle layer */}
          <g>
            {layout.links.map((l, i) => (
              <path
                key={`c-${l.id}`}
                ref={(el) => (pathRefs.current[i] = el)}
                d={centrePath(l)}
                fill="none"
                stroke="none"
              />
            ))}
          </g>
        </svg>

        {/* Particle stream sits above ribbons, below the labels */}
        <canvas
          ref={canvasRef}
          className="pointer-events-none absolute inset-0 z-[2]"
          aria-hidden="true"
        />

        {/* Gates + labels in the same SVG coordinate space, on top */}
        <svg
          width={width}
          height={HEIGHT}
          className="absolute inset-0 z-[3]"
          role="img"
          aria-label="Money flow diagram. A screen-reader table of the same figures follows."
        >
          {layout.nodes.map((n) => (
            <Gate
              key={n.id}
              node={n}
              total={layout.total}
              active={!hover || hover === n.id}
              onEnter={() => setHover(n.id)}
            />
          ))}
          {/* Hub caption + struck total */}
          <text
            x={hub.x0 + (hub.x1 - hub.x0) / 2}
            y={hub.y0 - 14}
            textAnchor="middle"
            className="fill-foreground font-display"
            stroke="hsl(var(--card))"
            strokeWidth={3}
            paintOrder="stroke"
            strokeLinejoin="round"
            style={{ fontSize: 12.5, letterSpacing: "0.08em" }}
          >
            TREASURY
          </text>
          <text
            x={hub.x0 + (hub.x1 - hub.x0) / 2}
            y={hub.y1 + 18}
            textAnchor="middle"
            className="fill-gold"
            stroke="hsl(var(--card))"
            strokeWidth={3}
            paintOrder="stroke"
            strokeLinejoin="round"
            style={{
              fontSize: 11,
              fontFamily: "'Spline Sans Mono', monospace",
              letterSpacing: "0.02em",
            }}
          >
            {formatCurrency(layout.total)}
          </text>
        </svg>

        {/* Paper vignette for depth — a struck plate, not a flat fill. */}
        <div
          className="pointer-events-none absolute inset-0 z-[4]"
          style={{
            boxShadow:
              "inset 0 0 60px hsl(var(--rule-strong) / 0.12), inset 0 1px 0 hsl(var(--background) / 0.4)",
          }}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-sans text-[11px] text-muted-foreground">
          {sources.length} source{sources.length === 1 ? "" : "s"} pour into the
          treasury; it drains to {sinks.length} channel
          {sinks.length === 1 ? "" : "s"}. Hover a gate to trace its flow.
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] text-muted-foreground">
          <LegendSwatch label="Income" varName="--credit" />
          <LegendSwatch label="Spending" varName="--chart-3" />
          <LegendSwatch
            label={layout.surplus >= 0 ? "Set aside" : "Reserves"}
            varName={layout.surplus >= 0 ? "--gold" : "--debit"}
          />
        </div>
      </div>

      {/* Accessible equivalent */}
      <table className="sr-only">
        <caption>Money flow by source and destination</caption>
        <tbody>
          {layout.nodes
            .filter((n) => n.side !== "hub")
            .map((n) => (
              <tr key={n.id}>
                <th scope="row">
                  {n.side === "source" ? "From" : "To"} {n.label}
                </th>
                <td>{formatCurrency(n.value)}</td>
                <td>{Math.round(n.share * 100)}% of flow</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function WindowSelect({
  days,
  setDays,
}: {
  days: number;
  setDays: (d: number) => void;
}) {
  return (
    <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
      <SelectTrigger className="w-44" aria-label="Time window">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {WINDOWS.map((w) => (
          <SelectItem key={w.value} value={String(w.value)}>
            {w.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function LegendSwatch({ label, varName }: { label: string; varName: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block h-2 w-3"
        style={{ background: `hsl(var(${varName}))`, opacity: 0.78 }}
      />
      {label}
    </span>
  );
}

function Readout({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "credit" | "debit" | "gold";
}) {
  const cls =
    tone === "credit" ? "text-credit" : tone === "gold" ? "text-gold" : "ink-debit";
  return (
    <div className="text-right">
      <dt className="dept-label">{label}</dt>
      <dd className={`ledger-figures text-lg ${cls}`}>{formatCurrency(value)}</dd>
    </div>
  );
}

function Gate({
  node,
  total,
  active,
  onEnter,
}: {
  node: FlowNode;
  total: number;
  active: boolean;
  onEnter: () => void;
}) {
  const isSource = node.side === "source";
  const isHub = node.side === "hub";
  // Labels read INWARD (d3-sankey convention) so they never clip the frame:
  // sources label to the right of their gate, sinks to the left.
  const labelX = isHub
    ? node.x0 + (node.x1 - node.x0) / 2
    : isSource
    ? node.x1 + 8
    : node.x0 - 8;
  const anchor = isHub ? "middle" : isSource ? "start" : "end";
  const midY = node.y0 + (node.y1 - node.y0) / 2;
  const color = kindColor(node.kind);
  const pct = Math.round((node.value / total) * 100);

  return (
    <g
      onMouseEnter={onEnter}
      style={{ cursor: "pointer", transition: "opacity 220ms" }}
      opacity={active ? 1 : 0.32}
    >
      {/* the lock gate */}
      <rect
        x={node.x0}
        y={node.y0}
        width={node.x1 - node.x0}
        height={Math.max(1, node.y1 - node.y0)}
        fill={color}
        fillOpacity={isHub ? 0.9 : 0.78}
        rx={1}
      />
      {/* a thin engraved keyline */}
      <rect
        x={node.x0}
        y={node.y0}
        width={node.x1 - node.x0}
        height={Math.max(1, node.y1 - node.y0)}
        fill="none"
        stroke="hsl(var(--background))"
        strokeOpacity={0.5}
        strokeWidth={0.75}
        rx={1}
      />
      {!isHub && node.y1 - node.y0 > 11 && (
        <>
          <text
            x={labelX}
            y={midY - 1}
            textAnchor={anchor}
            dominantBaseline="middle"
            className="fill-foreground font-display"
            stroke="hsl(var(--card))"
            strokeWidth={2.6}
            paintOrder="stroke"
            strokeLinejoin="round"
            style={{ fontSize: 11.5 }}
          >
            {node.label}
          </text>
          <text
            x={labelX}
            y={midY + 11}
            textAnchor={anchor}
            dominantBaseline="middle"
            className="fill-muted-foreground"
            stroke="hsl(var(--card))"
            strokeWidth={2.4}
            paintOrder="stroke"
            strokeLinejoin="round"
            style={{ fontSize: 9.5, fontFamily: "'Spline Sans Mono', monospace" }}
          >
            {formatCurrency(node.value)} · {pct}%
          </text>
        </>
      )}
    </g>
  );
}
