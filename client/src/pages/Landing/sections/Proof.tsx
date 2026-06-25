import { useRef } from "react";
import { useInView } from "motion/react";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Rise } from "../shared";

type Stat = { to: number; format: (n: number) => string; label: string };

const STATS: Stat[] = [
  { to: 12400, format: (n) => `${Math.round(n).toLocaleString()}+`, label: "accounts opened" },
  { to: 48, format: (n) => `$${Math.round(n)}M`, label: "forecast to the cent" },
  { to: 0, format: (n) => String(Math.round(n)), label: "surprise overdrafts" },
];

/** One stat that counts up from zero the first time it scrolls into view. */
function CountStat({ to, format, label }: Stat) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  return (
    <div ref={ref} className="bg-card px-4 py-7 text-center">
      <div className="intaglio text-foreground" style={{ fontSize: "clamp(1.6rem,4vw,2.4rem)" }}>
        <AnimatedNumber value={inView ? to : 0} format={format} duration={1200} />
      </div>
      <div className="mt-1.5 text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </div>
    </div>
  );
}

/** Proof strip — three engraved stats held "in good standing", counting up in view. */
export function Proof() {
  return (
    <section id="vault" className="mt-28">
      <Rise>
        <p className="section-rule mx-auto max-w-[1080px] text-[0.7rem] uppercase tracking-[0.28em] text-muted-foreground">
          Held in good standing
        </p>
        <div className="mt-6 grid grid-cols-1 gap-px border border-rule-strong/35 bg-rule-strong/25 sm:grid-cols-3">
          {STATS.map((s) => (
            <CountStat key={s.label} {...s} />
          ))}
        </div>
      </Rise>
    </section>
  );
}
