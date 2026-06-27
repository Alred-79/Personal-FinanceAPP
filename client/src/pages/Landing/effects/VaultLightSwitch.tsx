import { AnimatePresence, motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { useVaultLights } from "../hooks/useVaultLights";

/**
 * The vault light-switch — a physical brass switch bolted to the right wall of the
 * Midnight Vault. It exists ONLY in the dark zone (past the VaultDoor); flipping it
 * floods the vault back to parchment ("lights on") by overriding the scroll theme
 * journey, and flipping it again drops back into the dark.
 *
 * Gamey, not a generic toggle: an Edison filament bulb that warms up, a real
 * sliding switch knob with a spring throw, an engraved brass plate with screws.
 * Brass is hardcoded warm gold (theme-independent — it's a physical object, and in
 * the dark theme --gold is indigo). The warm bulb glow is the same amber as the
 * terminal's phosphor, tying the vault's light to the game world it leads into.
 *
 * a11y: a real <button> (≥44px), aria-pressed, descriptive aria-label, visible
 * focus ring, full keyboard. Reduced motion → no slide/throw, just appears + warms.
 */
export function VaultLightSwitch() {
  const { lightsOn, setLightsOn, inDarkZone } = useVaultLights();
  const reduce = useReducedMotion();

  const enter = reduce
    ? { opacity: { duration: 0.2 } }
    : { type: "spring" as const, stiffness: 240, damping: 26 };

  return (
    <AnimatePresence>
      {inDarkZone && (
        <motion.div
          className="fixed right-0 top-1/2 z-[55]"
          initial={
            reduce
              ? { opacity: 0, transform: "translate(0%,-50%)" }
              : { opacity: 0, transform: "translate(108%,-50%)" }
          }
          animate={{ opacity: 1, transform: "translate(0%,-50%)" }}
          exit={
            reduce
              ? { opacity: 0, transform: "translate(0%,-50%)" }
              : { opacity: 0, transform: "translate(108%,-50%)" }
          }
          transition={enter}
        >
          <button
            type="button"
            className="vls-plate"
            data-on={lightsOn}
            aria-pressed={lightsOn}
            aria-label={lightsOn ? "Turn the vault lights off" : "Turn the vault lights on"}
            onClick={() => setLightsOn(!lightsOn)}
          >
            <span className="vls-screw" aria-hidden />

            {/* Edison filament bulb */}
            <span className="vls-bulb" aria-hidden>
              <svg viewBox="0 0 32 44" width="34" height="46" fill="none">
                <path
                  className="vls-glass"
                  d="M16 3c-6 0-10 4.4-10 10 0 4 2 6.4 3.6 8.4 1.2 1.5 1.8 2.6 2 4.2h8.8c.2-1.6.8-2.7 2-4.2C24 19.4 26 17 26 13 26 7.4 22 3 16 3Z"
                  strokeWidth="1.5"
                />
                {/* filament */}
                <path className="vls-filament" d="M12.5 13.5c1.2-2.2 2-3 3.5-3s2.3.8 3.5 3M13.8 17.2c.9 1.4 1.4 1.9 2.2 1.9s1.3-.5 2.2-1.9" strokeWidth="1.3" strokeLinecap="round" />
                {/* cap */}
                <path d="M11.2 28h9.6M12 31.5h8M13 35h6l-.7 3.2c-.2.9-1 1.5-1.9 1.5h-.8c-.9 0-1.7-.6-1.9-1.5L13 35Z" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>

            {/* the sliding switch */}
            <span className="vls-track" aria-hidden>
              <motion.span
                className="vls-knob"
                animate={{ transform: lightsOn ? "translateY(0px)" : "translateY(22px)" }}
                transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 700, damping: 24 }}
              />
            </span>

            <span className="vls-state" aria-hidden>
              {lightsOn ? "ON" : "OFF"}
            </span>
            <span className="vls-screw" aria-hidden />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
