import { useFlags } from "@/store/gameMode";
import { GuillocheGL } from "./GuillocheGL";
import { LivingGuilloche } from "./LivingGuilloche";
import { BurinCursor } from "./BurinCursor";
import { MoodWatermark } from "./MoodWatermark";

/**
 * AtlasLayers — the global background/cursor chrome for the Cartographer's Desk,
 * mounted once in AppShell. Encapsulates all the mode gating so AppShell stays
 * tidy and no page branches on `mode` directly.
 *
 * - MoodWatermark: every mode (finance-derived).
 * - Guilloché: ambient + full get the WebGL flowing field (GuillocheGL); if
 *   WebGL fails it renders nothing and the CSS/canvas LivingGuilloche shows the
 *   lighter breathing fallback. off = nothing.
 * - BurinCursor: ambient + full (self-gates pointer:fine / reduce-motion).
 *
 * All layers are aria-hidden, behind content, never touch a money figure.
 */
export function AtlasLayers() {
  const flags = useFlags();
  const guilloche = flags.guillocheMotion || flags.guillocheWarp; // ambient + full

  return (
    <>
      <MoodWatermark />
      {guilloche && (
        <>
          {/* WebGL field on top; the canvas breather is the graceful fallback
              (it sits at the same z-0 and shows through if WebGL is absent). */}
          <LivingGuilloche />
          <GuillocheGL opacity={flags.guillocheWarp ? 0.55 : 0.42} />
        </>
      )}
      <BurinCursor />
    </>
  );
}
