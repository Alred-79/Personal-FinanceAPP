import { useMemo } from "react";
import { Color } from "three";

/** Resolve an HSL design token ("164 40% 22%") into a three.js Color. */
function colorFromVar(name: string, fallback: string): Color {
  const raw =
    (typeof window !== "undefined"
      ? getComputedStyle(document.documentElement)
          .getPropertyValue(name)
          .trim()
      : "") || fallback;
  const [h, s, l] = raw.split(/\s+/);
  const c = new Color();
  c.setStyle(`hsl(${h}, ${s}, ${l})`);
  return c;
}

export interface ReliquaryColors {
  gold: Color;
  credit: Color;
  glass: Color;
  bands: Color[];
}

/**
 * Reads the engraved palette from CSS tokens once on mount, so the scene inks
 * itself to Ledger Paper / Midnight Vault (mirrors GuillocheGL.readInk). A theme
 * flip while the vault is open re-inks on the next mount — acceptable for a hero
 * surface the user rarely theme-toggles mid-view.
 */
export function useReliquaryColors(): ReliquaryColors {
  return useMemo(
    () => ({
      gold: colorFromVar("--gold", "42 56% 44%"),
      credit: colorFromVar("--credit", "162 45% 26%"),
      glass: colorFromVar("--rule-strong", "162 16% 38%"),
      bands: ["--chart-1", "--chart-2", "--chart-4", "--chart-5", "--chart-6"].map(
        (v) => colorFromVar(v, "164 40% 26%")
      ),
    }),
    []
  );
}
