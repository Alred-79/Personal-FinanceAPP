import { Guilloche } from "@/components/engraving/Guilloche";
import { GuillocheGL } from "@/components/atlas/GuillocheGL";
import { GoldDust } from "@/components/atlas/GoldDust";
import { usePointerFine } from "@/hooks/useEnvironment";

/** Read the live theme ink from the landing root (where the journey toggles .dark). */
const landingRoot = () => document.querySelector(".landing-root");

/**
 * The living backdrop. A faint static guilloché rosette (always present, so
 * reduced-motion and WebGL-off visitors still get the engraved paper) with the
 * cursor-reactive WebGL guilloché field layered over it, muted. Pure chrome:
 * fixed, aria-hidden, pointer-events none, never near a money figure. Both layers
 * follow the light→dark journey (the field reads --gold from the landing root).
 */
export function Backdrop() {
  // The WebGL field + particles are desktop-only (fine pointer); touch devices
  // keep just the static engraved base to spare the GPU / battery.
  const fine = usePointerFine();
  return (
    <>
      <div
        aria-hidden
        className="pointer-events-none fixed left-1/2 top-[38%] -z-0 -translate-x-1/2 -translate-y-1/2 text-rule-strong/[0.08] dark:text-rule-strong/[0.12]"
      >
        <Guilloche size={920} rings={9} seed={421018 % 99991} />
      </div>
      {fine && <GuillocheGL opacity={0.46} colorSource={landingRoot} />}
      {fine && <GoldDust count={48} opacity={0.4} />}
    </>
  );
}
