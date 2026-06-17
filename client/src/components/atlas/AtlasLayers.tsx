import { useFlags } from "@/store/gameMode";
import { GuillocheGL } from "./GuillocheGL";
import { LivingGuilloche } from "./LivingGuilloche";
import { BurinCursor } from "./BurinCursor";
import { MoodWatermark } from "./MoodWatermark";
import { CursorGlow } from "./CursorGlow";

/**
 * AtlasLayers — the global background/cursor chrome for the Cartographer's Desk,
 * mounted once in AppShell. Encapsulates all the mode gating so AppShell stays
 * tidy and no page branches on `mode` directly.
 *
 * - MoodWatermark: every mode (finance-derived).
 * - LivingGuilloché: the light canvas "breather" — AMBIENT + full
 *   (`guillocheMotion`). Subtle (low opacity, --rule-strong), keeps content
 *   readable.
 * - GuillocheGL: the heavier WebGL phosphor field — FULL ONLY (`guillocheWarp`).
 *   This is the full-mode "living paper" centerpiece; keeping it off in ambient
 *   is what keeps ambient legible AND makes ambient→full a clear visual step.
 * - CursorGlow: soft warm glow — ambient + full.
 * - BurinCursor: ambient + full (self-gates pointer:fine / reduce-motion).
 *
 * All layers are aria-hidden, behind content, never touch a money figure.
 */
export function AtlasLayers() {
  const flags = useFlags();

  return (
    <>
      <MoodWatermark />
      {/* ambient + full: the subtle breathing rosette (self-gates internally too) */}
      {flags.guillocheMotion && <LivingGuilloche />}
      {/* full only: the WebGL phosphor field (off in ambient so content stays legible) */}
      {flags.guillocheWarp && <GuillocheGL opacity={0.45} />}
      {flags.guillocheMotion && <CursorGlow />}
      <BurinCursor />
    </>
  );
}
