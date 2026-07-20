import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * The maker's plate bolted to the apparatus. Flipping it doesn't open a separate
 * dossier — it turns this same machine over so you can read its workings: every
 * aperture states the mechanism it actually implements, and cites the file or
 * test that proves it.
 *
 * Brass is hardcoded warm gold, like the VaultLightSwitch: it is a physical
 * object on the wall, and in the dark theme --gold is indigo.
 */
export function EngineerSwitch({
  on,
  onChange,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  const reduce = useReducedMotion();

  return (
    <button
      type="button"
      className="rr-switch"
      data-on={on}
      aria-pressed={on}
      onClick={() => onChange(!on)}
    >
      <span className="rr-switch__screw" aria-hidden />
      <span className="rr-switch__body">
        <span className="rr-switch__label">Engineering proof</span>
        <span className="rr-switch__state" aria-hidden>
          {on ? "open" : "closed"}
        </span>
      </span>
      <span className="rr-switch__track" aria-hidden>
        <motion.span
          className="rr-switch__knob"
          animate={{ transform: on ? "translateX(20px)" : "translateX(0px)" }}
          transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 700, damping: 26 }}
        />
      </span>
      <span className="rr-switch__screw" aria-hidden />
    </button>
  );
}
