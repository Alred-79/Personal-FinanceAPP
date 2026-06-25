import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { Rise } from "../shared";

/** The mint — a struck "good standing" coin beside the reward copy. */
export function Mint() {
  const reduce = useReducedMotion();

  return (
    <section className="mt-28 grid grid-cols-1 items-center gap-10 sm:grid-cols-[auto_1fr]">
      <Rise className="justify-self-center sm:justify-self-start">
        <motion.div
          className="grid h-32 w-32 place-items-center rounded-full"
          style={{
            background:
              "radial-gradient(circle at 38% 32%, hsl(var(--gold)), hsl(42 56% 26%))",
            boxShadow:
              "0 10px 30px hsl(167 30% 12% / 0.4), inset 0 0 0 4px hsl(46 52% 96% / 0.25)",
          }}
          initial={reduce ? false : { rotateY: 180, scale: 1.6, opacity: 0 }}
          whileInView={{ rotateY: 0, scale: 1, opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7, ease: [0.34, 1.4, 0.64, 1] }}
          whileHover={reduce ? undefined : { rotateY: 18, rotateX: -10 }}
        >
          <span className="text-center font-display text-[0.85rem] font-semibold leading-tight tracking-[0.04em] text-[hsl(46_52%_96%)]">
            GOOD
            <br />
            STANDING
          </span>
        </motion.div>
      </Rise>
      <Rise delay={0.1}>
        <p className="dept-label">A reward worth keeping</p>
        <h2 className="mt-1 font-display font-semibold" style={{ fontSize: "clamp(1.6rem,4vw,2.4rem)" }}>
          Saving you'll actually finish.
        </h2>
        <p className="mt-3 max-w-[32rem] leading-relaxed text-muted-foreground">
          Every funded goal mints a specimen for your cabinet — proof of progress
          you can hold, not a streak you'll abandon. The only game your money
          should play.
        </p>
      </Rise>
    </section>
  );
}
