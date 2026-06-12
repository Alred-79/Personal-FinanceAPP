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
