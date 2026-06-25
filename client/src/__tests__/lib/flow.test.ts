import { describe, it, expect } from "vitest";
import { buildFlow, ribbonPath, centrePath } from "@/lib/flow";

const OPTS = { width: 800, height: 460 };

describe("buildFlow", () => {
  it("returns an empty layout when there is no money", () => {
    const l = buildFlow({ income: {}, expense: {} }, OPTS);
    expect(l.nodes).toHaveLength(0);
    expect(l.links).toHaveLength(0);
    expect(l.total).toBe(0);
  });

  it("balances surplus into a 'Set aside' sink", () => {
    const l = buildFlow(
      { income: { Salary: 5000 }, expense: { Rent: 2000, Food: 1000 } },
      OPTS
    );
    expect(l.surplus).toBe(2000);
    const saved = l.nodes.find((n) => n.label === "Set aside");
    expect(saved?.value).toBe(2000);
    expect(saved?.kind).toBe("saved");
    // income column total === sink column total === hub
    const sinkTotal = l.nodes
      .filter((n) => n.side === "sink")
      .reduce((s, n) => s + n.value, 0);
    expect(sinkTotal).toBe(5000);
    expect(l.total).toBe(5000);
  });

  it("balances a deficit into a 'Reserves drawn' source", () => {
    const l = buildFlow(
      { income: { Salary: 1000 }, expense: { Rent: 2000 } },
      OPTS
    );
    expect(l.surplus).toBe(-1000);
    const reserves = l.nodes.find((n) => n.label === "Reserves drawn");
    expect(reserves?.value).toBe(1000);
    expect(reserves?.kind).toBe("reserves");
    expect(l.total).toBe(2000);
  });

  it("folds the long tail into an 'Other spending' node", () => {
    const expense: Record<string, number> = {};
    for (let i = 0; i < 12; i++) expense[`Cat${i}`] = 12 - i; // descending
    const l = buildFlow({ income: { Pay: 1000 }, expense }, { ...OPTS, maxPerSide: 6 });
    const sinks = l.nodes.filter((n) => n.side === "sink");
    // 6 spending slots (5 top + 1 "Other spending") plus the "Set aside" surplus.
    expect(sinks.some((n) => n.label === "Other spending")).toBe(true);
    expect(sinks.filter((n) => n.kind === "spending")).toHaveLength(6);
  });

  it("links conserve flow: hub in-band height equals hub out-band height", () => {
    const l = buildFlow(
      { income: { A: 300, B: 700 }, expense: { X: 600, Y: 400 } },
      OPTS
    );
    const inBands = l.links
      .filter((k) => k.targetId === "hub")
      .reduce((s, k) => s + (k.ty1 - k.ty0), 0);
    const outBands = l.links
      .filter((k) => k.sourceId === "hub")
      .reduce((s, k) => s + (k.sy1 - k.sy0), 0);
    expect(inBands).toBeCloseTo(outBands, 5);
  });

  it("keeps every node inside the viewport bounds", () => {
    const l = buildFlow(
      { income: { A: 300, B: 700, C: 120 }, expense: { X: 600, Y: 400, Z: 90 } },
      OPTS
    );
    for (const n of l.nodes) {
      expect(n.y0).toBeGreaterThanOrEqual(0);
      expect(n.y1).toBeLessThanOrEqual(OPTS.height);
      expect(n.x0).toBeGreaterThanOrEqual(0);
      expect(n.x1).toBeLessThanOrEqual(OPTS.width);
    }
  });

  it("emits well-formed path strings", () => {
    const l = buildFlow(
      { income: { A: 1000 }, expense: { X: 1000 } },
      OPTS
    );
    const link = l.links[0];
    expect(ribbonPath(link)).toMatch(/^M[\d.,\s-]+ C.+Z$/);
    expect(centrePath(link)).toMatch(/^M[\d.,\s-]+ C/);
  });
});
