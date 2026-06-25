/**
 * Pure layout for the Money-Flow "watercourse" — a three-column Sankey where
 * every income source pours into one Treasury hub and the hub drains out to the
 * spending categories plus whatever is set aside. No React, no I/O, no DOM:
 * geometry in, geometry out, so the whole thing is unit-testable. Money is
 * dollars throughout.
 *
 * The diagram always balances: sum(sources) === sum(sinks) === hub.value. When
 * income exceeds spending the surplus becomes a "Set aside" sink; when spending
 * exceeds income the shortfall becomes a "Reserves drawn" source. That keeps
 * every ribbon's thickness honest at both ends (one global value→pixel scale).
 */

export interface FlowInput {
  /** Income by source/category → dollars (positive). */
  income: Record<string, number>;
  /** Spending by category → dollars (positive). */
  expense: Record<string, number>;
}

export interface FlowOptions {
  width: number;
  height: number;
  /** Width of a node "gate" in px. */
  nodeWidth?: number;
  /** Vertical gap between stacked nodes in a column, px. */
  gap?: number;
  /** Horizontal padding, px. */
  padX?: number;
  /** Vertical padding, px. */
  padY?: number;
  /** Collapse all but the top-N sources/sinks into an "Other" node. */
  maxPerSide?: number;
}

export type FlowSide = "source" | "hub" | "sink";

/** A semantic role drives colour in the renderer (no colours computed here). */
export type FlowKind =
  | "income"
  | "reserves"
  | "hub"
  | "spending"
  | "saved";

export interface FlowNode {
  id: string;
  label: string;
  value: number;
  side: FlowSide;
  kind: FlowKind;
  /** Share of the balanced total, 0..1. */
  share: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export interface FlowLink {
  id: string;
  sourceId: string;
  targetId: string;
  /** Colour follows this node's kind (the "moving" end the eye tracks). */
  kind: FlowKind;
  value: number;
  share: number;
  /** Ribbon band at the source (right edge of the left node). */
  x1: number;
  sy0: number;
  sy1: number;
  /** Ribbon band at the target (left edge of the right node). */
  x2: number;
  ty0: number;
  ty1: number;
}

export interface FlowLayout {
  nodes: FlowNode[];
  links: FlowLink[];
  width: number;
  height: number;
  totalIncome: number;
  totalExpense: number;
  /** income − expense (sign preserved). */
  surplus: number;
  /** The balanced total every column sums to. */
  total: number;
}

interface Entry {
  label: string;
  value: number;
}

/** Sort desc, drop non-positive, fold the tail past `max` into one "Other". */
function topN(rec: Record<string, number>, max: number, otherLabel: string): Entry[] {
  const entries = Object.entries(rec)
    .map(([label, value]) => ({ label, value }))
    .filter((e) => e.value > 0)
    .sort((a, b) => b.value - a.value);
  if (entries.length <= max) return entries;
  const head = entries.slice(0, max - 1);
  const tail = entries.slice(max - 1);
  const other = tail.reduce((s, e) => s + e.value, 0);
  if (other > 0) head.push({ label: otherLabel, value: other });
  return head;
}

const EMPTY = (width: number, height: number): FlowLayout => ({
  nodes: [],
  links: [],
  width,
  height,
  totalIncome: 0,
  totalExpense: 0,
  surplus: 0,
  total: 0,
});

export function buildFlow(input: FlowInput, opts: FlowOptions): FlowLayout {
  const {
    width,
    height,
    nodeWidth = 13,
    gap = 14,
    padX = 12,
    padY = 16,
    maxPerSide = 6,
  } = opts;

  const sources: Array<Entry & { kind: FlowKind }> = topN(
    input.income,
    maxPerSide,
    "Other income"
  ).map((e) => ({ ...e, kind: "income" as const }));
  const sinks: Array<Entry & { kind: FlowKind }> = topN(
    input.expense,
    maxPerSide,
    "Other spending"
  ).map((e) => ({ ...e, kind: "spending" as const }));

  const totalIncome = sources.reduce((s, e) => s + e.value, 0);
  const totalExpense = sinks.reduce((s, e) => s + e.value, 0);
  const surplus = totalIncome - totalExpense;

  // Balance the two columns so ribbon thickness is consistent end-to-end.
  if (surplus > 0) {
    sinks.push({ label: "Set aside", value: surplus, kind: "saved" });
  } else if (surplus < 0) {
    // Spent more than earned this period — the difference came from reserves.
    sources.push({ label: "Reserves drawn", value: -surplus, kind: "reserves" });
  }

  const total = Math.max(totalIncome, totalExpense);
  if (total <= 0 || width <= 0 || height <= 0) return EMPTY(width, height);

  // One global value→pixel scale, sized so the most-crowded column still fits.
  const usableH = height - 2 * padY;
  const maxNodes = Math.max(sources.length, sinks.length, 1);
  const scale = (usableH - (maxNodes - 1) * gap) / total;

  // Column x-positions: sources left, hub centre, sinks right.
  const srcX0 = padX;
  const sinkX0 = width - padX - nodeWidth;
  const hubX0 = (width - nodeWidth) / 2;

  const columnHeight = (n: number) => total * scale + (n - 1) * gap;
  const columnTop = (n: number) => padY + (usableH - columnHeight(n)) / 2;

  const nodes: FlowNode[] = [];

  // Stack a column of entries, returning each node's geometry in order.
  function stack(
    entries: Array<Entry & { kind: FlowKind }>,
    x0: number,
    side: FlowSide,
    idPrefix: string
  ): FlowNode[] {
    let y = columnTop(entries.length);
    return entries.map((e, i) => {
      const h = e.value * scale;
      const node: FlowNode = {
        id: `${idPrefix}-${i}`,
        label: e.label,
        value: e.value,
        side,
        kind: e.kind,
        share: e.value / total,
        x0,
        x1: x0 + nodeWidth,
        y0: y,
        y1: y + h,
      };
      y += h + gap;
      return node;
    });
  }

  const sourceNodes = stack(sources, srcX0, "source", "src");
  const sinkNodes = stack(sinks, sinkX0, "sink", "snk");

  const hubTop = columnTop(1);
  const hubNode: FlowNode = {
    id: "hub",
    label: "Treasury",
    value: total,
    side: "hub",
    kind: "hub",
    share: 1,
    x0: hubX0,
    x1: hubX0 + nodeWidth,
    y0: hubTop,
    y1: hubTop + total * scale,
  };

  nodes.push(...sourceNodes, hubNode, ...sinkNodes);

  const links: FlowLink[] = [];

  // Sources → hub: each source claims a band on the hub's left edge, in order.
  let hubLeftY = hubNode.y0;
  for (const sn of sourceNodes) {
    const band = sn.value * scale;
    links.push({
      id: `${sn.id}->hub`,
      sourceId: sn.id,
      targetId: hubNode.id,
      kind: sn.kind,
      value: sn.value,
      share: sn.share,
      x1: sn.x1,
      sy0: sn.y0,
      sy1: sn.y1,
      x2: hubNode.x0,
      ty0: hubLeftY,
      ty1: hubLeftY + band,
    });
    hubLeftY += band;
  }

  // Hub → sinks: each sink claims a band on the hub's right edge, in order.
  let hubRightY = hubNode.y0;
  for (const kn of sinkNodes) {
    const band = kn.value * scale;
    links.push({
      id: `hub->${kn.id}`,
      sourceId: hubNode.id,
      targetId: kn.id,
      kind: kn.kind,
      value: kn.value,
      share: kn.share,
      x1: hubNode.x1,
      sy0: hubRightY,
      sy1: hubRightY + band,
      x2: kn.x0,
      ty0: kn.y0,
      ty1: kn.y1,
    });
    hubRightY += band;
  }

  return {
    nodes,
    links,
    width,
    height,
    totalIncome,
    totalExpense,
    surplus,
    total,
  };
}

/** Closed ribbon outline (two cubic edges) for an SVG `<path d>` fill. */
export function ribbonPath(l: FlowLink): string {
  const mx = (l.x1 + l.x2) / 2;
  return (
    `M${l.x1},${l.sy0} ` +
    `C${mx},${l.sy0} ${mx},${l.ty0} ${l.x2},${l.ty0} ` +
    `L${l.x2},${l.ty1} ` +
    `C${mx},${l.ty1} ${mx},${l.sy1} ${l.x1},${l.sy1} Z`
  );
}

/** Single centre-line for sampling particle positions with getPointAtLength. */
export function centrePath(l: FlowLink): string {
  const sy = (l.sy0 + l.sy1) / 2;
  const ty = (l.ty0 + l.ty1) / 2;
  const mx = (l.x1 + l.x2) / 2;
  return `M${l.x1},${sy} C${mx},${sy} ${mx},${ty} ${l.x2},${ty}`;
}
