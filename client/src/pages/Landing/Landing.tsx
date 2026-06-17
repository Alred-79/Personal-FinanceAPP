import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion, useMotionValueEvent, useScroll } from "motion/react";
import { Guilloche, GuillocheBand } from "@/components/engraving/Guilloche";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";

/**
 * The Ledger — public marketing landing page, shown before /login.
 * A React port of design-prototypes/landing.html, re-skinned to the existing
 * "Engraver's Ledger" system (same tokens, primitives, color law). Money
 * figures stay sober (.figure / .intaglio); the gold accent decorates chrome
 * only. Standalone (no AppShell), like /login.
 */

const EASE = [0.22, 1, 0.36, 1] as const;

/** A scroll-triggered rise — reveals as the section enters the viewport. */
function Rise({
  children,
  className,
  delay = 0,
  y = 26,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.75, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  );
}

/** The institution's wax seal — a gold medallion with the £ monogram. */
function LedgerSeal({ size = 34, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-display font-semibold text-[hsl(46_52%_96%)]",
        className
      )}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.5,
        background:
          "radial-gradient(circle at 38% 32%, hsl(var(--gold)), hsl(42 56% 26%))",
        boxShadow:
          "inset 0 0 0 2px hsl(46 52% 96% / 0.3), 0 2px 8px hsl(167 30% 12% / 0.3)",
      }}
      aria-hidden
    >
      £
    </span>
  );
}

/** A live "accruing today" ticker — a tiny credit figure that climbs. */
function AccrualTicker() {
  const reduce = useReducedMotion();
  const [v, setV] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const id = setInterval(() => setV((x) => x + 0.0007 + Math.random() * 0.0006), 120);
    return () => clearInterval(id);
  }, [reduce]);
  return <span className="figure ink-credit">+${v.toFixed(4)}</span>;
}

const FEATURES = [
  {
    no: "No. 01",
    title: "The Sea-Chart",
    body: "Your cash-flow forecast as a coastline. Drag the line to model a what-if and watch your overdraft probability re-sound in real time. Probabilistic, not a flat guess.",
    icon: (
      <path d="M3 17c3-6 6-6 9 0s6 6 9 0M3 21h18" />
    ),
  },
  {
    no: "No. 02",
    title: "The Clerk",
    body: "An assistant that drafts the move — re-budget, schedule, reconcile — then hands you a diff plate to authorize. It proposes; you stamp. Nothing happens behind your back.",
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
  },
  {
    no: "No. 03",
    title: "Minted Goals",
    body: "Fund a goal and strike a coin for the cabinet. Saving becomes a collection of specimens you actually want to complete — the only game your money should play.",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 4v3M12 17v3M4 12h3M17 12h3" />
      </>
    ),
  },
  {
    no: "No. 04",
    title: "Import Anything",
    body: "Messy statements, mystery CSVs, duplicate rows. The Detangler reads them, reconciles them, and hands back a clean register — no manual category roulette.",
    icon: <path d="M4 5h16M4 12h16M4 19h10" />,
  },
  {
    no: "No. 05",
    title: "Nightly Auditor",
    body: "While you sleep, it reconciles the day, flags the odd charge, and leaves a short note in the margin. You wake up to an account already balanced.",
    icon: (
      <>
        <path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6Z" />
        <path d="M9 12l2 2 4-4" />
      </>
    ),
  },
  {
    no: "No. 06",
    title: "Tax, Filed Quietly",
    body: "1099s, deductions, quarterly estimates — tracked all year and stamped into a packet at season's end. The dread becomes a form you just sign.",
    icon: (
      <>
        <rect x="4" y="4" width="16" height="16" />
        <path d="M8 9h8M8 13h5" />
      </>
    ),
  },
];

const STEPS = [
  {
    idx: "i",
    title: "Open an account",
    body: "Sign the register. No card, no commitment — read-only access to start so nothing can move without you.",
  },
  {
    idx: "ii",
    title: "Bring your records",
    body: "Connect or import any statement. The Detangler cleans the mess and your first sea-chart inks itself within minutes.",
  },
  {
    idx: "iii",
    title: "Keep good standing",
    body: "The Clerk proposes, you stamp, the Auditor watches the nights. Your money stays legible, forever.",
  },
];

function FeatureIcon({ children }: { children: ReactNode }) {
  return (
    <span className="mb-4 grid h-11 w-11 place-items-center border border-rule-strong/50 text-gold">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
        {children}
      </svg>
    </span>
  );
}

export default function Landing() {
  const reduce = useReducedMotion();
  const { scrollY } = useScroll();
  const [shrunk, setShrunk] = useState(false);

  useMotionValueEvent(scrollY, "change", (y) => setShrunk(y > 40));

  // Smooth-scroll for the in-page anchor links; restore on unmount.
  useEffect(() => {
    const prev = document.documentElement.style.scrollBehavior;
    if (!reduce) document.documentElement.style.scrollBehavior = "smooth";
    return () => {
      document.documentElement.style.scrollBehavior = prev;
    };
  }, [reduce]);

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-background text-foreground">
      {/* living guilloché, breathing behind everything */}
      <div
        aria-hidden
        className="pointer-events-none fixed left-1/2 top-[38%] -z-0 -translate-x-1/2 -translate-y-1/2 text-rule-strong/[0.09] dark:text-rule-strong/[0.13]"
      >
        <Guilloche size={920} rings={9} seed={421018 % 99991} animate />
      </div>

      {/* top register / nav */}
      <nav
        className={cn(
          "fixed inset-x-0 top-0 z-40 flex items-center justify-between border-b border-rule-strong/35 bg-background/80 px-4 backdrop-blur transition-[padding] duration-300 sm:px-8",
          shrunk ? "py-2" : "py-3.5"
        )}
      >
        <div className="flex items-center gap-2.5">
          <LedgerSeal size={shrunk ? 30 : 34} className="transition-all duration-300" />
          <b className="font-display text-[1.05rem] font-semibold tracking-tight">The Ledger</b>
        </div>
        <div className="flex items-center gap-5 sm:gap-7">
          <a href="#features" className="hidden text-[0.82rem] text-muted-foreground transition-colors hover:text-foreground sm:inline">
            Instruments
          </a>
          <a href="#how" className="hidden text-[0.82rem] text-muted-foreground transition-colors hover:text-foreground sm:inline">
            How it works
          </a>
          <a href="#vault" className="hidden text-[0.82rem] text-muted-foreground transition-colors hover:text-foreground sm:inline">
            The Vault
          </a>
          <Link
            to="/login"
            className="press border border-rule-strong/60 px-3.5 py-2 text-[0.8rem] font-semibold uppercase tracking-[0.04em]"
          >
            Sign in
          </Link>
          <Link
            to="/login"
            className="press bg-primary px-3.5 py-2 text-[0.8rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground"
          >
            Open an account
          </Link>
        </div>
      </nav>

      <div className="relative z-[1] mx-auto max-w-[1080px] px-4 sm:px-8">
        {/* HERO */}
        <header
          className="grid content-start gap-6 pt-[clamp(7rem,16vh,11rem)] text-center"
          style={{ minHeight: "92vh" }}
        >
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
            <Link
              to="/login"
              className="press bg-primary px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground"
            >
              Open your ledger — free
            </Link>
            <a
              href="#features"
              className="press border border-rule-strong/60 px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em]"
            >
              See the instruments
            </a>
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

          {/* specimen note — the product shot */}
          <Rise className="mx-auto mt-12 w-full max-w-[760px]" delay={0.1}>
            <div className="plate plate-tilt relative bg-card p-6 text-left shadow-plate-lg">
              <div className="mb-4 text-gold/60">
                <GuillocheBand height={14} waves={4} seed={5} />
              </div>
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
                {[
                  { l: "Lowest point", v: "$240.10", c: "ink-credit" },
                  { l: "Reached on", v: "06-22", c: "" },
                  { l: "Outflows", v: "$1,910.00", c: "ink-debit" },
                  { l: "Net change", v: "+$1,030.18", c: "" },
                ].map((cell) => (
                  <div key={cell.l} className="bg-card px-3.5 py-2.5">
                    <div className="dept-label">{cell.l}</div>
                    <div className={cn("figure mt-1 text-[0.98rem]", cell.c)}>{cell.v}</div>
                  </div>
                ))}
              </div>
            </div>
          </Rise>
        </header>

        {/* PROOF */}
        <section id="vault" className="mt-28">
          <Rise>
            <p className="section-rule mx-auto max-w-[1080px] text-[0.7rem] uppercase tracking-[0.28em] text-muted-foreground">
              Held in good standing
            </p>
            <div className="mt-6 grid grid-cols-1 gap-px border border-rule-strong/35 bg-rule-strong/25 sm:grid-cols-3">
              {[
                { n: "12,400+", l: "accounts opened" },
                { n: "$48M", l: "forecast to the cent" },
                { n: "0", l: "surprise overdrafts" },
              ].map((s) => (
                <div key={s.l} className="bg-card px-4 py-7 text-center">
                  <div className="intaglio text-foreground" style={{ fontSize: "clamp(1.6rem,4vw,2.4rem)" }}>
                    {s.n}
                  </div>
                  <div className="mt-1.5 text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground">
                    {s.l}
                  </div>
                </div>
              ))}
            </div>
          </Rise>
        </section>

        {/* FEATURES */}
        <section id="features" className="mt-28">
          <Rise className="mx-auto max-w-[42rem] text-center">
            <p className="dept-label">The Instruments</p>
            <h2 className="mt-2 font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}>
              Every figure, engraved and accountable.
            </h2>
            <p className="mt-3 text-[1.02rem] text-muted-foreground">
              Not another dashboard of charts you ignore. Each tool is a working
              instrument — it does one thing, shows its reasoning, and never moves
              real money without your stamp.
            </p>
          </Rise>
          <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <Rise key={f.no} delay={(i % 3) * 0.07}>
                <article className="plate plate-tilt relative h-full bg-card p-6">
                  <span className="serial absolute right-4 top-4 font-mono text-[0.66rem] tracking-[0.16em] text-muted-foreground">
                    {f.no}
                  </span>
                  <FeatureIcon>{f.icon}</FeatureIcon>
                  <h3 className="font-display text-[1.22rem] font-semibold">{f.title}</h3>
                  <p className="mt-2 text-[0.92rem] leading-relaxed text-muted-foreground">{f.body}</p>
                </article>
              </Rise>
            ))}
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how" className="mt-28">
          <Rise>
            <p className="section-rule mx-auto max-w-[1080px] text-[0.7rem] uppercase tracking-[0.28em] text-muted-foreground">
              Three entries to open
            </p>
          </Rise>
          <div className="mt-8 border-t border-rule-strong/40">
            {STEPS.map((s, i) => (
              <Rise key={s.idx} delay={i * 0.06}>
                <div className="ledger-row group grid grid-cols-[auto_1fr_auto] items-center gap-6 border-b border-rule px-1 py-6">
                  <div className="w-10 font-display text-[1.8rem] text-gold">{s.idx}</div>
                  <div>
                    <h3 className="font-display text-[1.18rem] font-semibold">{s.title}</h3>
                    <p className="mt-1 text-[0.92rem] text-muted-foreground">{s.body}</p>
                  </div>
                  <span className="manicule text-[1.1rem]">☞</span>
                </div>
              </Rise>
            ))}
          </div>
        </section>

        {/* MINT */}
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

        {/* FINAL CTA */}
        <Rise className="mt-28">
          <section className="relative overflow-hidden border border-rule-strong/60 bg-card px-6 py-16 text-center sm:px-16">
            <div aria-hidden className="pointer-events-none absolute inset-1.5 border border-rule-strong/30" />
            <div className="relative flex flex-col items-center">
              <LedgerSeal size={48} className="mb-5" />
              <h2 className="font-display font-semibold" style={{ fontSize: "clamp(2rem,5vw,3.4rem)" }}>
                Your accounts, in good standing.
              </h2>
              <p className="mx-auto mt-3 max-w-[34rem] text-muted-foreground">
                Open the ledger today. It takes about two minutes, and you can read
                everything before you connect a thing.
              </p>
              <div className="mt-7 flex flex-wrap justify-center gap-3">
                <Link
                  to="/login"
                  className="press bg-primary px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground"
                >
                  Open your ledger — free
                </Link>
                <Link
                  to="/login"
                  className="press border border-rule-strong/60 px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em]"
                >
                  Sign in
                </Link>
              </div>
            </div>
          </section>
        </Rise>
      </div>

      {/* footer colophon */}
      <footer className="mt-20 border-t border-rule-strong/40 py-10">
        <div className="mx-auto flex max-w-[1080px] flex-wrap items-center justify-between gap-4 px-4 sm:px-8">
          <div className="flex items-center gap-2">
            <LedgerSeal size={28} />
            <b className="font-display text-[0.9rem] font-semibold">The Ledger</b>
          </div>
          <div className="flex gap-6">
            {["Privacy", "Security", "Terms", "Contact"].map((l) => (
              <span key={l} className="cursor-default text-[0.78rem] text-muted-foreground transition-colors hover:text-foreground">
                {l}
              </span>
            ))}
          </div>
          <p className="serial font-mono text-[0.7rem] tracking-[0.18em] text-muted-foreground">No. LK-42018</p>
        </div>
      </footer>
    </div>
  );
}
