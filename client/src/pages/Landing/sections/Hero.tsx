import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { GuillocheBand } from "@/components/engraving/Guilloche";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { AccrualTicker, AnchorLink, EASE, Rise } from "../shared";
import { CoinStage } from "../coin/CoinSceneLazy";
import { Foil } from "../effects/Foil";
import { SecurityWindow } from "../effects/SecurityWindow";
import { Magnetic } from "../effects/Magnetic";

const METRICS = [
  { l: "Lowest point", v: "$240.10", c: "ink-credit" },
  { l: "Reached on", v: "06-22", c: "" },
  { l: "Outflows", v: "$1,910.00", c: "ink-debit" },
  { l: "Net change", v: "+$1,030.18", c: "" },
];

/** The hero — department label, headline, lede, CTAs, assurances, specimen note. */
export function Hero() {
  const reduce = useReducedMotion();

  return (
    <header
      className="grid content-start gap-6 pt-[clamp(5.5rem,12vh,8rem)] text-center"
      style={{ minHeight: "92vh" }}
    >
      {/* the struck sovereign — the hero's interactive centrepiece */}
      <div className="pointer-events-auto mx-auto h-[clamp(190px,32vh,330px)] w-full max-w-[440px]">
        <CoinStage />
      </div>
      <motion.p
        className="dept-label"
        initial={reduce ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: EASE }}
      >
        Department of Personal Accounts · Est. MMXXVI
      </motion.p>
      <motion.h1
        className="mx-auto font-display font-semibold leading-[1.04] tracking-tight"
        style={{ fontSize: "clamp(2.6rem,7vw,5.2rem)" }}
        initial={reduce ? false : { opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.08 }}
      >
        Keep your money
        <br />
        in <span className="relative whitespace-nowrap text-gold">good standing</span>.
      </motion.h1>
      <motion.p
        className="mx-auto max-w-[40rem] text-muted-foreground"
        style={{ fontSize: "clamp(1rem,2.2vw,1.22rem)", lineHeight: 1.55 }}
        initial={reduce ? false : { opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.16 }}
      >
        The Ledger turns your accounts into engraved instruments you can actually
        read — a forecast you can drag, goals you can mint, and an assistant that
        proposes before it acts. No spreadsheets. No surprises.
      </motion.p>
      <motion.div
        className="mt-1 flex flex-wrap justify-center gap-3"
        initial={reduce ? false : { opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.24 }}
      >
        <Magnetic>
          <Link
            to="/login"
            className="press inline-block bg-primary px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground"
          >
            Open your ledger — free
          </Link>
        </Magnetic>
        <AnchorLink
          to="#features"
          className="press border border-rule-strong/60 px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em]"
        >
          See the instruments
        </AnchorLink>
      </motion.div>
      <motion.div
        className="mt-3 flex flex-wrap justify-center gap-6 text-[0.72rem] tracking-[0.04em] text-muted-foreground"
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.32 }}
      >
        {["No card required", "Your data stays yours", "Read-only by default"].map((t) => (
          <span key={t} className="flex items-center gap-1.5">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className="text-gold">
              <path d="M20 6 9 17l-5-5" />
            </svg>
            {t}
          </span>
        ))}
      </motion.div>

      {/* specimen note — the product shot, as a polymer "security window" */}
      <Rise className="mx-auto mt-12 w-full max-w-[760px]" delay={0.1}>
        <SecurityWindow className="p-6 text-left shadow-plate-lg">
          {/* holographic security strip */}
          <Foil className="mb-4 text-gold/60">
            <GuillocheBand height={16} waves={5} seed={5} />
          </Foil>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="dept-label">Projected balance · Form 90</p>
              <div className="intaglio mt-1 text-foreground" style={{ fontSize: "clamp(2rem,6vw,3.4rem)" }}>
                $4,210.18
              </div>
              <p className="mt-1.5 text-[0.85rem] text-muted-foreground">
                accruing today · <AccrualTicker />
              </p>
            </div>
            <p className="serial font-mono text-[0.7rem] tracking-[0.18em] text-muted-foreground">
              No. LK-42018
            </p>
          </div>
          <div className="mt-5 grid grid-cols-2 gap-px border border-rule-strong/30 bg-rule-strong/20 sm:grid-cols-4">
            {METRICS.map((cell) => (
              <div key={cell.l} className="bg-card px-3.5 py-2.5">
                <div className="dept-label">{cell.l}</div>
                <div className={cn("figure mt-1 text-[0.98rem]", cell.c)}>{cell.v}</div>
              </div>
            ))}
          </div>
        </SecurityWindow>
      </Rise>
    </header>
  );
}
