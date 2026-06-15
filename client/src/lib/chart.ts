/**
 * Shared recharts styling so every chart reads as the same engraved plate.
 * Colours resolve through CSS variables at runtime, so charts re-ink when the
 * theme flips between Ledger Paper and Midnight Vault.
 */

function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** hsl(var(--x)) wrapped for recharts string props. */
export function ink(name: string, alpha = 1): string {
  const v = cssVar(name);
  return alpha === 1 ? `hsl(${v})` : `hsl(${v} / ${alpha})`;
}

export const AXIS_TICK = {
  fontFamily: "'Spline Sans Mono', monospace",
  fontSize: 10,
};

export function tooltipStyle() {
  return {
    background: ink("--popover"),
    border: `1px solid ${ink("--rule-strong", 0.5)}`,
    borderRadius: 0,
    fontFamily: "'Spline Sans Mono', monospace",
    fontSize: 11,
    color: ink("--popover-foreground"),
    boxShadow: "0 8px 24px hsl(167 30% 12% / 0.18)",
  };
}

/**
 * Steel-engraving hatch fill (frontend-elevation). Returns the SVG markup for a
 * diagonal line-hatch <pattern> in a chart ink, plus the `url(#id)` reference to
 * use as an area `fill`. Reads like an engraved plate instead of a flat gradient.
 *
 * Usage in a recharts chart:
 *   <defs dangerouslySetInnerHTML={{ __html: hatch("h-run", "--chart-3").def }} />
 *   <Area fill={hatch("h-run", "--chart-3").fill} ... />
 * (id must be unique per chart instance.)
 */
export function hatch(id: string, colorVar: string, alpha = 0.5, gap = 5) {
  const stroke = ink(colorVar, alpha);
  return {
    fill: `url(#${id})`,
    def: `<pattern id="${id}" patternUnits="userSpaceOnUse" width="${gap}" height="${gap}" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="${gap}" stroke="${stroke}" stroke-width="1" />
    </pattern>`,
  };
}
