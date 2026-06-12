/**
 * Seeded ASCII creature art (v4 §7.1, package 06).
 *
 * A deterministic glyph-grid creature derived from
 * ``seed = hash(kind + creditor_or_merchant_normalized)`` via a mirrored-mask
 * algorithm: a seeded PRNG fills a half-grid with density values, we mirror it
 * left↔right (creatures are symmetric, which reads as a face/body), then map
 * density → a glyph ramp. Same seed → identical art on every run and platform
 * (recognition is the whole point). Size tiers scale with the balance bucket.
 *
 * No randomness from Math.random — everything flows from the seed, so the grid
 * is reproducible in tests and across clients.
 */

/** A small, fast, fully-deterministic string hash (FNV-1a, 32-bit). */
export function hashSeed(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** A mulberry32 PRNG seeded from a 32-bit integer — deterministic sequence. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Density → glyph ramp (sparse → dense). Index 0 is empty. */
const GLYPH_RAMP = [" ", ".", ":", "+", "*", "#", "@"];

export type CreatureKind = "credit_card" | "loan" | "bnpl" | "other" | "monster";

/** Balance buckets → grid size tier (rows). Bigger debt = bigger creature. */
export function sizeTier(balanceCents: number): number {
  if (balanceCents >= 1_000_000) return 11; // >= $10k
  if (balanceCents >= 300_000) return 9; // >= $3k
  if (balanceCents >= 50_000) return 7; // >= $500
  return 5;
}

export interface CreatureSpec {
  kind: CreatureKind;
  /** Creditor or merchant name; normalized (lowercased, trimmed) before hashing. */
  name: string;
  balanceCents?: number;
}

function normalize(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * Generate the creature as an array of row strings. Deterministic in the spec.
 * Width is odd so the mirror has a center column.
 */
export function asciiCreature(spec: CreatureSpec): string[] {
  const seed = hashSeed(`${spec.kind}:${normalize(spec.name)}`);
  const rng = mulberry32(seed);
  const rows = sizeTier(spec.balanceCents ?? 0);
  const half = Math.ceil(rows / 2) + 1; // half-width (excl. center); full width = half*2+1

  const grid: string[] = [];
  for (let r = 0; r < rows; r++) {
    const halfCells: number[] = [];
    for (let c = 0; c < half; c++) {
      // Bias density toward the body center and top (head) for a creature feel.
      const edgeFalloff = 1 - c / half;
      const v = rng() * (0.45 + 0.55 * edgeFalloff);
      const density = Math.min(GLYPH_RAMP.length - 1, Math.floor(v * GLYPH_RAMP.length));
      halfCells.push(density);
    }
    // Center column: average of the innermost cell, for a spine.
    const center = halfCells[0];
    const left = halfCells.map((d) => GLYPH_RAMP[d]);
    const right = [...halfCells].reverse().map((d) => GLYPH_RAMP[d]);
    grid.push([...right, GLYPH_RAMP[center], ...left].join(""));
  }
  return grid;
}

/** A single string (newline-joined) — convenience for <pre> rendering. */
export function asciiCreatureText(spec: CreatureSpec): string {
  return asciiCreature(spec).join("\n");
}
