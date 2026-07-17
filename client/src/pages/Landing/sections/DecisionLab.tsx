import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import {
  BASE_SAFE_TO_SPEND,
  DAYS,
  DEMO_SCENARIOS,
  scenarioNet,
  simulate,
  smoothPath,
  type DemoScenario,
  type SimResult,
} from "./forecast/sim";

const W = 680;
const H = 268;
const PAD_X = 34;
const PAD_TOP = 18;
const PAD_BOTTOM = 30;
const BAL_MIN = -1800;
const BAL_MAX = 3200;

const xFor = (day: number) => PAD_X + (day / (DAYS - 1)) * (W - PAD_X * 2);
const yFor = (balance: number) =>
  PAD_TOP +
  (1 - (balance - BAL_MIN) / (BAL_MAX - BAL_MIN)) *
    (H - PAD_TOP - PAD_BOTTOM);

const dollars = (value: number) => {
  const rounded = Math.round(value);
  return `${rounded < 0 ? "−" : ""}$${Math.abs(rounded).toLocaleString()}`;
};

const percent = (value: number) => `${Math.round(value * 100)}%`;

function bandPath(result: SimResult) {
  const high = result.high.map((balance, day) => [xFor(day), yFor(balance)] as [number, number]);
  const low = result.low
    .map((balance, day) => [xFor(day), yFor(balance)] as [number, number])
    .reverse();
  return `${smoothPath(high)} ${smoothPath(low).replace(/^M/, "L")} Z`;
}

function linePath(result: SimResult) {
  return smoothPath(result.med.map((balance, day) => [xFor(day), yFor(balance)]));
}

function signed(value: number, suffix = "") {
  if (value === 0) return `No change${suffix}`;
  return `${value > 0 ? "+" : "−"}${suffix}${Math.abs(Math.round(value)).toLocaleString()}`;
}

/**
 * Anonymous public Decision Lab. It uses a deterministic sample ledger and the
 * same forecast shape as the product, but never asks for or transmits visitor data.
 */
export function DecisionLab() {
  const reduce = useReducedMotion();
  const [selected, setSelected] = useState<DemoScenario>(
    () => DEMO_SCENARIOS.find((scenario) => scenario.key === "flight") ?? DEMO_SCENARIOS[0]
  );
  const baseline = useMemo(() => simulate(), []);
  const projection = useMemo(
    () => simulate({ scenarioNet: scenarioNet(selected) }),
    [selected]
  );

  const safeToSpend = BASE_SAFE_TO_SPEND + selected.safeDelta;
  const safeDelta = safeToSpend - BASE_SAFE_TO_SPEND;
  const probabilityDelta = projection.prob - baseline.prob;
  const liveSummary = `${selected.label}. Safe to spend ${dollars(
    safeToSpend
  )}, modeled low ${dollars(projection.troughMed)}, overdraft probability ${percent(
    projection.prob
  )}.`;

  return (
    <section className="decision-lab" aria-labelledby="decision-lab-title">
      <div className="decision-lab__mast">
        <div>
          <p className="decision-lab__folio">Illustrative 30-day ledger</p>
          <h2 id="decision-lab-title">Test a decision before it becomes a transaction.</h2>
        </div>
        <span className="decision-lab__sample">Sample data</span>
      </div>

      <div className="decision-lab__choices" aria-label="Choose a sample what-if">
        {DEMO_SCENARIOS.map((scenario) => {
          const active = scenario.key === selected.key;
          return (
            <button
              key={scenario.key}
              type="button"
              className="decision-lab__choice"
              aria-pressed={active}
              onClick={() => setSelected(scenario)}
            >
              <span>{scenario.label}</span>
              <small>{scenario.detail}</small>
            </button>
          );
        })}
      </div>

      <div className="decision-lab__chart-wrap">
        <svg
          className="decision-lab__chart"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-labelledby="decision-chart-title decision-chart-desc"
        >
          <title id="decision-chart-title">Baseline and what-if cash-flow projection</title>
          <desc id="decision-chart-desc">
            A 30-day modeled balance range comparing the sample ledger with {selected.label.toLowerCase()}.
          </desc>
          <defs>
            <pattern
              id="decision-hatch"
              width="7"
              height="7"
              patternTransform="rotate(45)"
              patternUnits="userSpaceOnUse"
            >
              <line
                x1="0"
                y1="0"
                x2="0"
                y2="7"
                stroke="hsl(var(--gold))"
                strokeWidth="1"
                opacity="0.32"
              />
            </pattern>
          </defs>

          {[3000, 2000, 1000, 0, -1000].map((tick) => (
            <g key={tick} aria-hidden="true">
              <line
                x1={PAD_X}
                x2={W - PAD_X}
                y1={yFor(tick)}
                y2={yFor(tick)}
                stroke="hsl(var(--rule-strong))"
                strokeOpacity={tick === 0 ? 0.48 : 0.15}
                strokeDasharray={tick === 0 ? "5 5" : undefined}
              />
              <text
                x={PAD_X}
                y={yFor(tick) - 6}
                fill="hsl(var(--muted-foreground))"
                fontFamily="'Spline Sans Mono', monospace"
                fontSize="9"
              >
                {tick === 0 ? "$0" : `${tick < 0 ? "−" : ""}$${Math.abs(tick) / 1000}k`}
              </text>
            </g>
          ))}

          <path
            d={bandPath(baseline)}
            fill="hsl(var(--credit) / 0.06)"
            stroke="hsl(var(--credit) / 0.24)"
            strokeWidth="1"
          />
          <path
            d={linePath(baseline)}
            fill="none"
            stroke="hsl(var(--credit) / 0.52)"
            strokeWidth="2"
            strokeDasharray="5 5"
          />
          <motion.path
            d={bandPath(projection)}
            fill="url(#decision-hatch)"
            stroke="hsl(var(--gold) / 0.7)"
            strokeWidth="1.2"
            initial={false}
            animate={{ d: bandPath(projection) }}
            transition={reduce ? { duration: 0 } : { duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
          />
          <motion.path
            d={linePath(projection)}
            fill="none"
            stroke="hsl(var(--foreground))"
            strokeWidth="2.8"
            strokeLinecap="round"
            initial={false}
            animate={{ d: linePath(projection) }}
            transition={reduce ? { duration: 0 } : { duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
          />

          <text x={PAD_X} y={H - 8} className="decision-lab__axis-label">
            Today
          </text>
          <text x={W / 2} y={H - 8} textAnchor="middle" className="decision-lab__axis-label">
            Day 15
          </text>
          <text x={W - PAD_X} y={H - 8} textAnchor="end" className="decision-lab__axis-label">
            Day 30
          </text>
        </svg>
        <div className="decision-lab__legend" aria-hidden="true">
          <span><i className="decision-lab__key decision-lab__key--base" />Baseline</span>
          <span><i className="decision-lab__key decision-lab__key--scenario" />What if</span>
        </div>
      </div>

      <dl className="decision-lab__results">
        <div>
          <dt>Safe to spend</dt>
          <dd>{dollars(safeToSpend)}</dd>
          <span className={safeDelta >= 0 ? "ink-credit" : "ink-debit"}>
            {signed(safeDelta, "$")} vs. baseline
          </span>
        </div>
        <div>
          <dt>Modeled low · ~90% range</dt>
          <dd>{dollars(projection.troughMed)}</dd>
          <span>
            {dollars(projection.troughLow)} to {dollars(projection.troughHigh)}
          </span>
        </div>
        <div>
          <dt>Chance below $0</dt>
          <dd>{percent(projection.prob)}</dd>
          <span className={probabilityDelta <= 0 ? "ink-credit" : "ink-debit"}>
            {probabilityDelta === 0
              ? "No change"
              : `${probabilityDelta > 0 ? "+" : "−"}${Math.abs(
                  Math.round(probabilityDelta * 100)
                )} points`}
          </span>
        </div>
      </dl>

      <p className="sr-only" aria-live="polite">{liveSummary}</p>

      <div className="decision-lab__foot">
        <p>240 modeled futures · amounts are illustrative, not financial advice</p>
        <Link className="decision-lab__cta press" to="/login">
          Run this with my numbers <span aria-hidden>→</span>
        </Link>
      </div>
    </section>
  );
}
