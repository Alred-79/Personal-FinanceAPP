import { ReactNode } from "react";
import { Rise } from "../../shared";
import { useTilt } from "../../hooks/useTilt";

const GOLD = "hsl(var(--gold))";
const CREDIT = "hsl(var(--credit))";
const DEBIT = "hsl(var(--debit))";

/** Step 1 — walk the recurring ledger into a balance line. */
function WalkLedger() {
  return (
    <svg viewBox="0 0 220 96" className="ftk" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <line x1="14" y1="80" x2="206" y2="80" className="ftk-rule" strokeWidth="1" />
      <path className="ftk-walk" d="M14 34 H54 V52 H92 V40 H128 V62 H164 V48 H206" stroke={CREDIT} strokeWidth="2.4" />
      <g stroke={DEBIT} strokeWidth="2">
        <path d="M54 52v8M128 62v8" />
      </g>
      <g stroke={CREDIT} strokeWidth="2">
        <path d="M92 40v-8M164 48v-8" />
      </g>
    </svg>
  );
}

/** Step 2 — many resampled futures fan out. */
function FanFutures() {
  const lines = [22, 34, 44, 52, 60, 70, 80];
  return (
    <svg viewBox="0 0 220 96" className="ftk" fill="none" stroke="currentColor" strokeLinecap="round">
      <g className="ftk-fan" stroke={GOLD} strokeWidth="1.2" opacity="0.5">
        {lines.map((y, i) => (
          <path key={i} d={`M14 50 C 80 50, 120 ${y}, 206 ${y + (i - 3) * 2}`} />
        ))}
      </g>
      <circle cx="14" cy="50" r="3.4" fill={GOLD} stroke="none" />
      <path d="M14 50 C 80 50, 120 52, 206 50" stroke={CREDIT} strokeWidth="2.4" />
    </svg>
  );
}

/** Step 3 — a calibrated corridor forms around the median. */
function CalibrateBand() {
  return (
    <svg viewBox="0 0 220 96" className="ftk" fill="none" stroke="currentColor" strokeLinecap="round">
      <defs>
        <pattern id="ftk-hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="0" y2="6" stroke={GOLD} strokeWidth="1" opacity="0.25" />
        </pattern>
      </defs>
      <path
        className="ftk-band"
        d="M14 34 C 80 30, 130 24, 206 30 L206 64 C 130 58, 80 70, 14 60 Z"
        fill="url(#ftk-hatch)"
        stroke={GOLD}
        strokeOpacity="0.4"
        strokeWidth="1"
        strokeDasharray="3 3"
      />
      <path d="M14 47 C 80 46, 130 42, 206 47" stroke={CREDIT} strokeWidth="2.4" />
    </svg>
  );
}

/** Step 4 — a change-point flag where the spending pace shifts. */
function CatchShift() {
  return (
    <svg viewBox="0 0 220 96" className="ftk" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <line x1="14" y1="62" x2="120" y2="62" stroke={CREDIT} strokeWidth="2.4" opacity="0.55" />
      <path className="ftk-step" d="M120 62 L120 38 L206 38" stroke={CREDIT} strokeWidth="2.4" />
      <line className="ftk-flagpole" x1="120" y1="62" x2="120" y2="18" stroke={GOLD} strokeWidth="1.6" strokeDasharray="2 3" />
      <path className="ftk-flag" d="M120 20 h22 l-6 6 6 6 h-22 Z" fill={GOLD} stroke="none" opacity="0.9" />
    </svg>
  );
}

type Step = { n: string; title: string; caption: string; art: ReactNode };

const STEPS: Step[] = [
  {
    n: "i",
    title: "Walk your ledger",
    caption: "Your recurring bills and paychecks form a deterministic baseline, summed forward one day at a time from today's balance.",
    art: <WalkLedger />,
  },
  {
    n: "ii",
    title: "Simulate the futures",
    caption: "A block bootstrap draws thousands of Monte Carlo futures, resampling your daily spending in weekly windows so real streaks survive instead of averaging away.",
    art: <FanFutures />,
  },
  {
    n: "iii",
    title: "Calibrate the band",
    caption: "Conformal calibration widens the corridor until its empirical coverage reaches about 90 percent, then widens it further as your variance rises.",
    art: <CalibrateBand />,
  },
  {
    n: "iv",
    title: "Catch the shift",
    caption: "A CUSUM change point test flags when your spending rate breaks from its running mean and reweights the estimate toward the new regime.",
    art: <CatchShift />,
  },
];

/** One method step as a live plate: cursor-tracking 3D tilt + gold sheen + the
 *  art lifting off the page, with its bespoke scene drawing in on hover. */
function MethodCard({ s, index }: { s: Step; index: number }) {
  const { ref, enabled, handlers } = useTilt(7);
  return (
    <Rise delay={(index % 4) * 0.06} className="h-full">
      <div className="ftk-tilt h-full">
        <div ref={ref} {...handlers} className="ftk-card plate h-full bg-card p-5">
          {enabled && <span aria-hidden className="ftk-sheen" />}
          <div className="flex items-center gap-2.5">
            <span className="font-display text-[1.3rem] text-gold">{s.n}</span>
            <h4 className="font-display text-[1.02rem] font-semibold">{s.title}</h4>
          </div>
          <div className="ftk-stage mt-3 text-gold">{s.art}</div>
          <p className="mt-3 text-[0.84rem] leading-relaxed text-muted-foreground">
            {s.caption}
          </p>
        </div>
      </div>
    </Rise>
  );
}

/** How the forecast thinks — the real engine's reasoning, in four engraved steps. */
export function HowItThinks() {
  return (
    <div className="mt-16">
      <Rise className="text-center">
        <p className="dept-label">How the forecast thinks</p>
        <h3 className="mt-1.5 font-display font-semibold" style={{ fontSize: "clamp(1.3rem,3vw,1.9rem)" }}>
          Not a guess. A method.
        </h3>
      </Rise>
      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((s, i) => (
          <MethodCard key={s.n} s={s} index={i} />
        ))}
      </div>
    </div>
  );
}
