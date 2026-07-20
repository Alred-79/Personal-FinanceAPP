import { cn } from "@/lib/utils";
import { Cite } from "./Cite";
import type { Tier } from "./specimenData";

/**
 * A verification level, rendered in its own register.
 *
 * The three levels are deliberately NOT three copies of one list — currency
 * grades its security features by the instrument you check them with, and each
 * instrument gets its own treatment here:
 *
 *   I   naked eye     full ink, solid ledger rules, two columns. Nothing to
 *                     qualify, so nothing qualifies it.
 *   II  raking lamp   a lamp-wash across the band, dashed rules, and every
 *                     entry led by a REQUIRES strip in brass — the precondition
 *                     is the first thing read, not a footnote under the fold.
 *   III microscope    a dark plate, because these ship dark. Each entry is led
 *                     by its flag in mono, set like a slide label.
 *
 * The gate line for II and III is structural, not decorative: it is rendered
 * before the body, and specimenData's contract (enforced in the test suite)
 * refuses to let a II or III entry exist without one.
 */
export function TierRegister({ tier }: { tier: Tier }) {
  const gateLabel = tier.id === "iii" ? "Held shut by" : "Requires";

  return (
    <section
      className={cn("spx-tier", `spx-tier--${tier.id}`)}
      aria-labelledby={`spx-tier-${tier.id}`}
    >
      <header className="spx-tier__head">
        <span className="spx-tier__lensmark" aria-hidden>
          <TierLens id={tier.id} />
        </span>
        <div className="spx-tier__title">
          <h3 id={`spx-tier-${tier.id}`} className="spx-tier__name">
            <span className="spx-tier__level">Level {tier.numeral}</span>
            {tier.name}
          </h3>
          <p className="spx-tier__lens">{tier.lens}</p>
        </div>
        <p className="spx-tier__rule">{tier.rule}</p>
      </header>

      <dl className="spx-tier__list">
        {tier.entries.map((e) => (
          <div className="spx-row" key={e.title}>
            <dt className="spx-row__title">{e.title}</dt>
            <dd className="spx-row__body">
              {e.gate && (
                <p className="spx-gate">
                  <span className="spx-gate__label">{gateLabel}</span>
                  <span className="spx-gate__text">{e.gate}</span>
                </p>
              )}
              <p className="spx-row__text">{e.body}</p>
              <ul className="spx-row__cites">
                {e.proof.map((c) => (
                  <li key={`${c.path}${c.symbol ?? ""}`}>
                    <Cite {...c} compact />
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * The instrument each level is checked with, engraved rather than iconified:
 * an open eye, a lamp raking across a surface, a microscope over a slide.
 */
function TierLens({ id }: { id: Tier["id"] }) {
  const common = {
    viewBox: "0 0 44 44",
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  if (id === "i") {
    return (
      <svg {...common}>
        <path d="M6 22c5-8 27-8 32 0-5 8-27 8-32 0Z" strokeWidth="1.6" />
        <circle cx="22" cy="22" r="6" strokeWidth="1.4" />
        <circle cx="22" cy="22" r="2" fill="currentColor" stroke="none" />
        <g strokeWidth="1.1" opacity="0.5">
          <path d="M22 8V4M8 13l-3-3M36 13l3-3M22 36v4" />
        </g>
      </svg>
    );
  }
  if (id === "ii") {
    return (
      <svg {...common}>
        {/* the lamp, angled low over the sheet */}
        <path d="M9 6v9" strokeWidth="1.4" />
        <path d="M4 15h10l-3 7H7Z" strokeWidth="1.5" />
        {/* the raking beam */}
        <g strokeWidth="1.1" opacity="0.65">
          <path d="M13 24l9 8M17 22l12 10M21 21l14 11" />
        </g>
        {/* the surface it rakes across, and the mark it lifts */}
        <path d="M6 38h32" strokeWidth="1.5" />
        <path d="M28 33h7" strokeWidth="1.4" opacity="0.85" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      {/* eyepiece + tube */}
      <path d="M20 5h7" strokeWidth="1.5" />
      <path d="M21 7h5v9h-5Z" strokeWidth="1.4" />
      <path d="M23.5 16v6" strokeWidth="1.4" />
      {/* objective and arm */}
      <path d="M20 22h7l-3.5 6Z" strokeWidth="1.5" />
      <path d="M27 10c6 3 8 11 4 17" strokeWidth="1.2" opacity="0.6" />
      {/* the stage, with a slide on it */}
      <path d="M12 31h23" strokeWidth="1.5" />
      <path d="M17 31v-2h13v2" strokeWidth="1.1" opacity="0.6" />
      <path d="M15 38h17" strokeWidth="1.4" />
      <path d="M23.5 31v7" strokeWidth="1.2" />
    </svg>
  );
}
