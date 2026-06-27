import { useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { HP_START_CENTS, MIN_CENTS, aprHeal, dollars, dollarsCents } from "./gameData";
import { BeastStage } from "./beast/BeastStage";

/**
 * The Debt Boss — the REAL seeded debt (Sapphire Card, $842.13 @ 23.99% APR) as a
 * minted-gold beast you fell by paying it down from a FINITE savings reserve. You
 * DRAW BACK a strike (hold to wind up) — the longer you draw, the faster the
 * payment climbs (it accelerates), so a heavy blow is hard to control and easy to
 * overspend. Every strike is real cash leaving your savings ("You spent $X"); APR
 * interest heals the beast back, so timid jabs let it regenerate. Fell it before
 * your savings run dry. A CC0 3D rig dissolves to the real remaining balance;
 * reduced-motion / no-WebGL get the engraved SVG beast.
 */

const START_HP = HP_START_CENTS; // 84_213 = $842.13
const START_SAVINGS = 100_000; // $1,000 — tight: flailing / minimum-only runs it dry
const TAP_MAX_MS = 130; // a quick tap = a clean $35 jab
const MAX_CHARGE = 40_000; // $400 — the runaway ceiling of a long draw
const FULL_MS = 2_000; // hold-time to reach MAX (convex → accelerating)

/** payment for a draw held `ms`: a tap is a min jab; a longer hold winds up along
 *  a convex (accelerating) curve, so control falls away the further you draw. */
function paymentForHold(ms: number): number {
  if (ms <= TAP_MAX_MS) return MIN_CENTS;
  const t = Math.min(1, (ms - TAP_MAX_MS) / FULL_MS);
  return Math.round(MIN_CENTS + (MAX_CHARGE - MIN_CENTS) * t * t);
}

type Float = { id: number; spent: number; heal: number };

// ── the engraved SVG fallback beast (reduced-motion / no-WebGL) ───────────────
const CRACKS = [
  { d: "M62 38 66 56 58 68", at: 0.18 },
  { d: "M92 42 86 60 96 76", at: 0.42 },
  { d: "M48 84 64 94", at: 0.64 },
  { d: "M104 82 88 96", at: 0.84 },
];
function SvgBeast({ frac, hit, dead, reduce }: { frac: number; hit: number; dead: boolean; reduce: boolean }) {
  const d = 1 - frac;
  const color = `hsl(6 ${Math.round(8 + frac * 66)}% ${Math.round(60 + d * 14)}%)`;
  const slump = `translateY(${(d * 12).toFixed(1)}px) rotate(${(-d * 6).toFixed(1)}deg) scale(${(1 - d * 0.12).toFixed(3)})`;
  return (
    <div className="arc-beast2" key={hit} data-shake={!reduce && hit > 0 ? hit : undefined}>
      <svg viewBox="0 0 150 132" width="180" height="158" fill="none" aria-hidden
        style={{ color, opacity: dead ? 0 : 0.34 + frac * 0.66, transform: slump,
          transition: reduce ? "none" : "opacity .5s var(--ease-out), transform .55s var(--ease-out), color .5s" }}>
        <g stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round">
          <path d="M44 44C30 34 22 20 24 8c12 4 22 14 28 28" style={{ opacity: 0.35 + frac * 0.65 }} />
          <path d="M106 44c14-10 22-24 20-36-12 4-22 14-28 28" style={{ opacity: 0.35 + frac * 0.65 }} />
          <path d="M75 30c24 0 40 16 40 38 0 22-18 44-40 44S35 90 35 68c0-22 16-38 40-38Z" />
          <path d="M48 60c8-6 16-7 22-3M102 60c-8-6-16-7-22-3" />
          <path d="M52 66c5-1 9 2 9 6s-4 6-9 5-7-4-6-7 3-3 6-4Z" fill="currentColor" stroke="none" style={{ opacity: frac }} />
          <path d="M98 66c-5-1-9 2-9 6s4 6 9 5 7-4 6-7-3-3-6-4Z" fill="currentColor" stroke="none" style={{ opacity: frac }} />
          {d > 0.82 && <g strokeWidth="1.6"><path d="M48 64l8 8M56 64l-8 8M94 64l8 8M102 64l-8 8" /></g>}
          <path d="M66 86c4 4 14 4 18 0" />
          <path d="M64 90l4 8 4-7M86 90l-4 8-4-7" style={{ opacity: 0.45 + frac * 0.55 }} />
          {CRACKS.map((c, i) => (
            <path key={i} d={c.d} strokeWidth="1.2" style={{ opacity: d > c.at ? 0.85 : 0, transition: reduce ? "none" : "opacity .4s var(--ease-out)" }} />
          ))}
        </g>
      </svg>
    </div>
  );
}

export function DebtBoss() {
  const reduce = useReducedMotion();
  const [hp, setHp] = useState<number>(START_HP);
  const [savings, setSavings] = useState<number>(START_SAVINGS);
  const [months, setMonths] = useState(0);
  const [interestLost, setInterestLost] = useState(0);
  const [floats, setFloats] = useState<Float[]>([]);
  const [hitN, setHitN] = useState(0);
  const [draw, setDraw] = useState<number | null>(null); // live payment while drawing

  const drawing = useRef(false);
  const startMs = useRef(0);
  const raf = useRef(0);
  const fid = useRef(0);

  const won = hp <= 0;
  const bankrupt = savings <= 0 && hp > 0;
  const frac = Math.max(0, hp / START_HP);
  const live = draw ?? MIN_CENTS;
  const spent = START_SAVINGS - savings;

  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  function strike(payment: number) {
    if (won || bankrupt) return;
    const actualToDebt = Math.min(payment, hp); // what lands on the balance
    const fromSavings = Math.min(actualToDebt, savings); // can't spend what you don't have
    if (fromSavings <= 0) return;
    const afterPay = hp - fromSavings;
    const heal = afterPay > 0 ? aprHeal(afterPay) : 0;
    setHp(afterPay + heal);
    setSavings((s) => Math.max(0, s - fromSavings));
    setMonths((m) => m + 1);
    setInterestLost((x) => x + heal);
    setHitN((n) => n + 1);
    const id = ++fid.current;
    setFloats((f) => [...f, { id, spent: fromSavings, heal }]);
    if (!reduce) window.setTimeout(() => setFloats((f) => f.filter((x) => x.id !== id)), 1100);
    else setFloats((f) => f.slice(-1));
  }

  function startDraw(e: React.PointerEvent) {
    if (won || bankrupt || drawing.current) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drawing.current = true;
    startMs.current = performance.now();
    setDraw(MIN_CENTS);
    const tick = () => {
      if (!drawing.current) return;
      setDraw(paymentForHold(performance.now() - startMs.current));
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }
  function loose() {
    if (!drawing.current) return;
    drawing.current = false;
    cancelAnimationFrame(raf.current);
    const payment = paymentForHold(performance.now() - startMs.current);
    setDraw(null);
    strike(payment);
  }
  function onKey(e: React.KeyboardEvent) {
    if ((e.key === "Enter" || e.key === " ") && !drawing.current) {
      e.preventDefault();
      strike(MIN_CENTS);
    }
  }

  function reset() {
    setHp(START_HP);
    setSavings(START_SAVINGS);
    setMonths(0);
    setInterestLost(0);
    setFloats([]);
    setHitN(0);
  }

  // memoized so the 60fps draw-charge re-renders never re-render the 3D canvas
  const beast = useMemo(
    () => (
      <BeastStage
        health={frac}
        phase={won ? "dead" : "idle"}
        hitKey={hitN}
        fallback={<SvgBeast frac={frac} hit={hitN} dead={won} reduce={reduce} />}
      />
    ),
    [frac, won, hitN, reduce]
  );

  const tension = Math.min(1, (live - MIN_CENTS) / (MAX_CHARGE - MIN_CENTS));
  const savingsFrac = Math.max(0, savings / START_SAVINGS);
  const over = drawing.current && live > savings; // drawing more than you can afford

  return (
    <div className="arc-game arc-boss">
      <div className="arc-boss__intro">
        <p className="arc-boss__lead">What this shows you</p>
        <p className="arc-boss__caption">
          Your debt is a beast; its health is the real balance. Draw a strike from your savings and
          loose it — the longer you draw, the faster the cost climbs, so a heavy blow is easy to
          overspend. Interest heals the beast, so timid jabs let it regrow. Fell it before your
          savings run dry.
        </p>
      </div>

      <div className="arc-arena">
        <div
          className={`arc-beastwrap ${drawing.current ? "is-drawing" : ""}`}
          onPointerDown={startDraw}
          onPointerUp={loose}
          onPointerLeave={loose}
          onPointerCancel={loose}
          onKeyDown={onKey}
          role="button"
          tabIndex={won || bankrupt ? -1 : 0}
          aria-label="Hold to draw back a strike from your savings, release to loose"
        >
          <div
            className="arc-beast3d"
            style={{ transform: `scale(${(1 - tension * 0.05).toFixed(3)}) translateY(${(tension * 10).toFixed(1)}px)` }}
          >
            {beast}
          </div>

          {/* floats: what you spent (debit) + interest the beast healed back */}
          <div className="arc-hits2" aria-hidden>
            {floats.map((f) => (
              <span key={f.id} className="arc-hit2-group">
                <span className="arc-hit2 arc-hit2--spent figure ledger-figures">You spent {dollarsCents(f.spent)}</span>
                {f.heal > 0 && (
                  <span className="arc-hit2 arc-hit2--heal figure ledger-figures">beast healed +{dollarsCents(f.heal)}</span>
                )}
              </span>
            ))}
          </div>

          {/* live draw readout / hint / end states */}
          {won ? (
            <div className="arc-verdict arc-verdict--win" role="status">
              <span className="arc-win__seal">✦</span>
              <p className="arc-win__title">VANQUISHED</p>
              <p className="arc-win__sub">
                Felled in <b className="figure ledger-figures">{months}</b> {months === 1 ? "month" : "months"} ·{" "}
                <b className="figure ledger-figures ink-credit">{dollars(savings)}</b> savings to spare ·{" "}
                <b className="figure ledger-figures ink-debit">{dollars(interestLost)}</b> to interest
              </p>
              <button type="button" className="arc-btn" onClick={reset}>face it again</button>
            </div>
          ) : bankrupt ? (
            <div className="arc-verdict arc-verdict--lose" role="status">
              <p className="arc-win__title">SAVINGS DRY</p>
              <p className="arc-win__sub">
                You burned through your savings and the beast still stands at{" "}
                <b className="figure ledger-figures ink-debit">{dollarsCents(hp)}</b>. Interest wins the war of attrition.
              </p>
              <button type="button" className="arc-btn" onClick={reset}>try again</button>
            </div>
          ) : drawing.current ? (
            <div className={`arc-draw ${over ? "is-over" : tension > 0.55 ? "is-hot" : ""}`}>
              <span className="arc-draw__amt figure ledger-figures">{dollarsCents(live)}</span>
              <span className="arc-draw__note">{over ? "more than you have!" : "drawing back — release to strike"}</span>
            </div>
          ) : (
            <div className="arc-draw__hint">hold &amp; draw back · release to strike</div>
          )}
        </div>

        {/* savings reserve — drains with every strike; run dry and you lose */}
        <div className="arc-savings" aria-label={`Savings ${dollars(savings)}`}>
          <span className="arc-savings__cap">SAVINGS</span>
          <div className="arc-savings__track">
            <span className="arc-savings__fill" style={{ transform: `scaleY(${savingsFrac})` }} />
          </div>
          <span className="arc-savings__val figure ledger-figures">{dollars(savings)}</span>
        </div>
      </div>

      {/* HP = the real remaining balance */}
      <div className="arc-hp" role="meter" aria-valuenow={Math.round(hp / 100)} aria-valuemin={0} aria-valuemax={Math.round(START_HP / 100)} aria-label={`Debt remaining ${dollars(hp)}`}>
        <span className="arc-hp__fill" style={{ transform: `scaleX(${frac})` }} />
        <span className="arc-hp__read figure ledger-figures">{dollarsCents(hp)}</span>
      </div>

      <div className="arc-boss__stats">
        <div className="arc-stat"><span className="arc-stat__num figure ledger-figures ink-debit">{dollars(spent)}</span><span className="arc-stat__label">cash spent</span></div>
        <div className="arc-stat"><span className="arc-stat__num figure ledger-figures">{months}</span><span className="arc-stat__label">months in</span></div>
        <div className="arc-stat"><span className="arc-stat__num figure ledger-figures ink-debit">{dollars(interestLost)}</span><span className="arc-stat__label">lost to interest</span></div>
      </div>

      <p className="arc-foot">real $842.13 balance · 23.99% apr · the in-app boss works exactly like this</p>
    </div>
  );
}
