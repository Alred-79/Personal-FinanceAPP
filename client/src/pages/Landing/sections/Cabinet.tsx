import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { Rise } from "../shared";
import { CabinetScene } from "./cabinetVisuals";

const REWARDS = [
  {
    title: "Goals Cabinet",
    body: "Fund a goal and strike a coin for the cabinet — a collection of specimens you'll actually want to complete.",
  },
  {
    title: "The Bestiary",
    body: "Your debts become beasts in a bestiary. Whittle each balance down to nothing and fell it for good — no grinding, just paying.",
  },
  {
    title: "Campaigns",
    body: "Every season opens a campaign — a quarter-long challenge you seal with a medal once the arc is done.",
  },
];

/**
 * The Cabinet — the product's reward / game layer, gathered so the struck
 * "good standing" coin no longer stands alone. The coin leads; the three real
 * surfaces (Goals, the Debts Bestiary, Campaigns) follow as tactile specimens.
 */
export function Cabinet() {
  const reduce = useReducedMotion();

  return (
    <section className="mt-28">
      <div className="grid grid-cols-1 items-center gap-10 sm:grid-cols-[auto_1fr]">
        <Rise className="justify-self-center sm:justify-self-start">
          <motion.div
            className="grid h-32 w-32 place-items-center rounded-full"
            style={{
              background: "radial-gradient(circle at 38% 32%, hsl(var(--gold)), hsl(42 56% 26%))",
              boxShadow: "0 10px 30px hsl(167 30% 12% / 0.4), inset 0 0 0 4px hsl(46 52% 96% / 0.25)",
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
            Money, made a game worth finishing.
          </h2>
          <p className="mt-3 max-w-[34rem] leading-relaxed text-muted-foreground">
            Saving, paying down debt, the long quarters — the parts you'd usually dread
            become specimens you collect, beasts you fell, and campaigns you seal. Proof
            of progress you can hold, not a streak you'll abandon.
          </p>
        </Rise>
      </div>

      <div className="mt-14 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {REWARDS.map((r, i) => (
          <Rise key={r.title} delay={(i % 3) * 0.06}>
            <article className="cab-card plate h-full bg-card p-5">
              <div className="cab-stage text-gold">
                <CabinetScene index={i} />
              </div>
              <h3 className="font-display text-[1.1rem] font-semibold">{r.title}</h3>
              <p className="mt-2 text-[0.9rem] leading-relaxed text-muted-foreground">{r.body}</p>
            </article>
          </Rise>
        ))}
      </div>
    </section>
  );
}
