import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { GuillocheBand } from "@/components/engraving/Guilloche";
import { usePointerFine, useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { EASE } from "../shared";
import { DemoLink } from "../demo";
import { CoinStage } from "../coin/CoinSceneLazy";
import type { CoinSide } from "../coin/coinFace";
import { Foil } from "../effects/Foil";
import { SecurityWindow } from "../effects/SecurityWindow";
import { Magnetic } from "../effects/Magnetic";
import { ReadOnlyBadge } from "@/components/custom/Trust/ReadOnlyBadge";

/** How long the coin rests on the bank's side before turning itself over. */
const AUTO_FLIP_MS = 1800;

// One illustrative month. The arithmetic is exact: 3,480.18 − 1,650.00 − 412.00
// − 208.00 = 1,210.18. Sample figures, labelled as such on the plate.
const BALANCE = "$3,480.18";
const SAFE = "$1,210.18";
const SPOKEN_FOR = [
  { label: "Rent", note: "due in 6 days", value: "−$1,650.00" },
  { label: "Card payment", note: "due in 3 days", value: "−$412.00" },
  { label: "4 smaller bills", note: "phone, internet & 2 more", value: "−$208.00" },
];

const READOUT: Record<CoinSide, { label: string; figure: string; note: string }> = {
  balance: {
    label: "What your bank says",
    figure: BALANCE,
    note: "Looks like plenty. But some of it is already spoken for.",
  },
  safe: {
    label: "Safe to spend · until payday in 9 days",
    figure: SAFE,
    note: "After every bill already headed out of the account.",
  },
};

/** The two-sided coin's accessible control: a labelled pair of radios. */
function SideToggle({ side, onPick }: { side: CoinSide; onPick: (s: CoinSide) => void }) {
  const options: { value: CoinSide; label: string }[] = [
    { value: "balance", label: "Bank balance" },
    { value: "safe", label: "Safe to spend" },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Which side of the coin to show"
      className="inline-grid grid-cols-2 border border-rule-strong/50 bg-card/70 p-1"
    >
      {options.map((o) => {
        const on = side === o.value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onPick(o.value)}
            className={cn(
              "press min-h-11 px-3.5 text-[0.74rem] font-semibold uppercase tracking-[0.05em] transition-colors duration-200",
              on ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** The plate the coin sits on: the coin beside the figure for the side showing,
 *  the arithmetic that turns the balance into the safe-to-spend number, and the
 *  flip control underneath. */
function LedgerPlate({
  side,
  coin,
  controls,
}: {
  side: CoinSide;
  coin: ReactNode;
  controls: ReactNode;
}) {
  const reduce = useReducedMotion();
  const safe = side === "safe";
  const r = READOUT[side];

  return (
    <SecurityWindow className="p-5 text-left shadow-plate-lg sm:p-6">
      <div className="mb-3 flex items-center gap-3">
        <Foil className="min-w-0 flex-1 text-gold/60">
          <GuillocheBand height={14} waves={5} seed={5} />
        </Foil>
        <p className="serial shrink-0 font-mono text-[0.66rem] tracking-[0.16em] text-muted-foreground">
          Sample
        </p>
      </div>

      <div className="flex items-center gap-3 sm:gap-4">
        <div className="-my-2 -ml-2 h-[118px] w-[118px] shrink-0 sm:h-[148px] sm:w-[148px]">{coin}</div>
        <div aria-live="polite" className="min-w-0">
          <p className="dept-label">{r.label}</p>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={side}
              className="intaglio mt-1 text-foreground"
              style={{ fontSize: "clamp(1.9rem,4.4vw,2.8rem)" }}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: 6, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6, filter: "blur(4px)" }}
              transition={{ duration: 0.2, ease: EASE }}
            >
              {r.figure}
            </motion.div>
          </AnimatePresence>
          <p className="mt-1 text-pretty text-[0.86rem] leading-snug text-muted-foreground">{r.note}</p>
        </div>
      </div>

      {/* the working: always on the page, inked in when the safe side shows */}
      <dl className="hero-ledger mt-5 border-t border-rule-strong/30 text-[0.88rem]" data-side={side}>
        <div className="hero-ledger__row" data-active={!safe || undefined}>
          <dt>Balance</dt>
          <dd className="figure">{BALANCE}</dd>
        </div>
        {SPOKEN_FOR.map((line, i) => (
          <div
            key={line.label}
            className="hero-ledger__row hero-ledger__debit"
            style={{ transitionDelay: safe && !reduce ? `${80 + i * 70}ms` : "0ms" }}
          >
            <dt>
              {line.label} <span className="text-muted-foreground">· {line.note}</span>
            </dt>
            <dd className="figure ink-debit">{line.value}</dd>
          </div>
        ))}
        <div
          className="hero-ledger__row hero-ledger__total"
          data-active={safe || undefined}
          style={{ transitionDelay: safe && !reduce ? "320ms" : "0ms" }}
        >
          <dt className="font-semibold">Safe to spend until payday</dt>
          <dd className="figure font-semibold">{SAFE}</dd>
        </div>
      </dl>

      <div className="mt-4">{controls}</div>
    </SecurityWindow>
  );
}

/**
 * The hero. One promise — know what is safe to spend before payday — shown as a
 * two-sided coin: the bank's balance on one face, the safe-to-spend number on
 * the other. The coin turns itself over once, then it's the visitor's to flip.
 */
export function Hero() {
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  // Reduced motion starts on the answer; everyone else watches the coin turn.
  const [side, setSide] = useState<CoinSide>(reduce ? "safe" : "balance");
  const touched = useRef(false);

  useEffect(() => {
    if (reduce) return;
    const id = window.setTimeout(() => {
      if (!touched.current) setSide("safe");
    }, AUTO_FLIP_MS);
    return () => window.clearTimeout(id);
  }, [reduce]);

  const pick = (s: CoinSide) => {
    touched.current = true;
    setSide(s);
  };

  // Keep every word legible on the first frame. Opacity never starts at zero,
  // so a paused animation, background tab, or headless renderer cannot blank
  // the promise or the CTA.
  const arrival = (y: number) => (reduce ? false : { opacity: 0.94, y, filter: "blur(0.5px)" });
  const settle = { opacity: 1, y: 0, filter: "blur(0px)" };

  return (
    <header
      className="grid content-center items-center gap-10 pb-6 pt-[clamp(6rem,13vh,8.5rem)] text-center lg:min-h-[94vh] lg:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] lg:gap-14 lg:text-left"
    >
      <div className="grid gap-6">
        <motion.h1
          className="text-balance font-display font-semibold leading-[1.04] tracking-tight"
          style={{ fontSize: "clamp(2.5rem,5.4vw,4.4rem)" }}
          initial={arrival(16)}
          animate={settle}
          transition={{ duration: 0.7, ease: EASE }}
        >
          Know what&rsquo;s <span className="text-gold">safe to spend</span> before payday.
        </motion.h1>
        <motion.p
          className="mx-auto max-w-[36rem] text-pretty text-muted-foreground lg:mx-0"
          style={{ fontSize: "clamp(1.02rem,1.6vw,1.2rem)", lineHeight: 1.55 }}
          initial={arrival(14)}
          animate={settle}
          transition={{ duration: 0.7, ease: EASE, delay: 0.08 }}
        >
          Your bank shows a balance. The Ledger subtracts the rent, bills, and card
          payments already headed out of it, so you see what you can actually spend,
          with the math right underneath.
        </motion.p>
        <motion.div
          className="flex flex-wrap justify-center gap-3 lg:justify-start"
          initial={arrival(12)}
          animate={settle}
          transition={{ duration: 0.7, ease: EASE, delay: 0.16 }}
        >
          <Magnetic>
            <DemoLink className="press inline-block bg-primary px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground">
              Try the demo
            </DemoLink>
          </Magnetic>
          <Link
            to="/login"
            className="press border border-rule-strong/60 px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em]"
          >
            Open your ledger
          </Link>
        </motion.div>
        <motion.div
          className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-[0.74rem] tracking-[0.03em] text-muted-foreground lg:justify-start"
          initial={reduce ? false : { opacity: 0.94 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.7, ease: EASE, delay: 0.24 }}
        >
          <ReadOnlyBadge label="Read-only by default · nothing moves without you" />
          {["Demo needs no signup", "No product kickbacks"].map((t) => (
            <span key={t} className="flex items-center gap-1.5">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className="text-gold" aria-hidden>
                <path d="M20 6 9 17l-5-5" />
              </svg>
              {t}
            </span>
          ))}
        </motion.div>
      </div>

      {/* two sides of the same money */}
      <motion.div
        className="mx-auto w-full max-w-[480px]"
        initial={reduce ? false : { opacity: 0.9, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.9, ease: EASE, delay: 0.1 }}
      >
        <LedgerPlate
          side={side}
          coin={
            <div className="h-full w-full" onPointerDownCapture={() => (touched.current = true)}>
              <CoinStage side={side} onSideChange={setSide} />
            </div>
          }
          controls={
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <SideToggle side={side} onPick={pick} />
              <p className="text-[0.74rem] text-muted-foreground">
                Two sides of the same money. {fine ? "Drag or click" : "Tap"} the coin.
              </p>
            </div>
          }
        />
      </motion.div>
    </header>
  );
}
