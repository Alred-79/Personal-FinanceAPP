import { useRef } from "react";
import { motion, useTransform } from "motion/react";
import { Guilloche } from "@/components/engraving/Guilloche";
import { useThemeJourney } from "../hooks/useThemeJourney";

/**
 * The threshold between "Ledger Paper" (light) and the "Midnight Vault" (dark).
 * A tall section with a sticky engraved door-dial that turns as you scroll; at
 * the midpoint a vault curtain washes over the viewport and the theme flips
 * beneath it, so the page emerges on the dark side. See useThemeJourney.
 */
export function VaultDoor() {
  const ref = useRef<HTMLElement>(null);
  const { curtain, progress, reduce } = useThemeJourney(ref);

  const doorRotate = useTransform(progress, [0, 1], [-45, 215]);
  const doorScale = useTransform(progress, [0, 0.5, 1], [0.86, 1.08, 0.86]);
  const labelOpacity = useTransform(progress, [0, 0.3, 0.5, 0.7, 1], [0, 1, 1, 1, 0]);

  return (
    <section ref={ref} className="relative my-8 h-[110vh]">
      <motion.div
        className="sticky top-0 grid h-screen content-center justify-items-center gap-5 px-4 text-center"
        style={reduce ? undefined : { opacity: labelOpacity }}
      >
        <p className="dept-label">Vault · Your control</p>
        <h2
          className="font-display font-semibold"
          style={{ fontSize: "clamp(1.8rem,5vw,3rem)" }}
        >
          Nothing moves without you.
        </h2>
        <p className="mx-auto max-w-[34rem] leading-relaxed text-muted-foreground">
          Below this line, the same ledger reveals how every connection, answer,
          and proposed action stays inside a boundary you can inspect.
        </p>
        <motion.div
          aria-hidden
          className="mt-3 text-gold/55"
          style={reduce ? undefined : { rotate: doorRotate, scale: doorScale }}
        >
          <Guilloche size={232} rings={7} seed={70713} animate={!reduce} />
        </motion.div>
      </motion.div>

      {/* the veil that masks the instant theme flip at the midpoint */}
      {!reduce && (
        <motion.div
          aria-hidden
          className="vault-curtain pointer-events-none fixed inset-0 z-[60] grid place-items-center"
          style={{ opacity: curtain }}
        >
          <div className="text-gold/35">
            <Guilloche size={540} rings={9} seed={9043} animate />
          </div>
        </motion.div>
      )}
    </section>
  );
}
