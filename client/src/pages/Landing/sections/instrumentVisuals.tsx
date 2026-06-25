/**
 * Bespoke engraved "specimen" scenes for each instrument plate. Each is a small
 * SVG that idles gently and comes alive on plate hover — the animations live in
 * landing.css, keyed off `.iv-tilt:hover` (and reused across scenes).
 * Stroke = currentColor (the stage is tinted gold); credit/debit inks are set
 * directly so the colour law still reads.
 */

const CREDIT = "hsl(var(--credit))";
const DEBIT = "hsl(var(--debit))";

/** No.03 — Subscriptions Watch: recurring rows on the left, a price-creep tick on the right. */
function Subscriptions() {
  return (
    <svg viewBox="0 0 300 116" className="iv" fill="none" stroke="currentColor">
      {/* a slowly turning "recurring" glyph */}
      <g className="iv-sun" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <path d="M40 34a13 13 0 1 0 4-9" />
        <path d="M40 18v8h8" />
      </g>
      {/* the recurring charges, drawing in on hover */}
      <g className="iv-rows" strokeWidth="2" strokeLinecap="round" stroke={CREDIT}>
        <line x1="20" y1="66" x2="120" y2="66" />
        <line x1="20" y1="82" x2="120" y2="82" />
        <line x1="20" y1="98" x2="96" y2="98" />
      </g>
      {/* price creep — a stepped line rising to a flagged peak */}
      <line className="iv-sea-od" x1="158" y1="78" x2="286" y2="78" strokeWidth="1" stroke={DEBIT} strokeDasharray="4 5" />
      <path className="iv-sea-line" d="M160 90 H196 V72 H232 V54 H286" stroke={DEBIT} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <circle className="iv-sea-node" cx="286" cy="54" r="4.6" fill="hsl(var(--gold))" stroke="hsl(var(--background))" strokeWidth="1.6" />
    </svg>
  );
}

/** No.02 — The Clerk: a diff plate the assistant drafts; you stamp it. */
function Clerk() {
  return (
    <svg viewBox="0 0 300 116" className="iv" fill="none" stroke="currentColor">
      <g strokeWidth="2" strokeLinecap="round">
        <line className="iv-add" x1="26" y1="34" x2="176" y2="34" stroke={CREDIT} />
        <line className="iv-del" x1="26" y1="58" x2="150" y2="58" stroke={DEBIT} />
        <line x1="26" y1="82" x2="166" y2="82" className="iv-rule" strokeWidth="1.4" />
      </g>
      <g stroke="none" fontFamily="'Spline Sans Mono', monospace" fontSize="15" fontWeight="700">
        <text x="10" y="39" fill={CREDIT}>+</text>
        <text className="iv-del-mark" x="11" y="63" fill={DEBIT}>–</text>
      </g>
      <g className="iv-stamp" stroke="currentColor">
        <circle cx="250" cy="58" r="22" strokeWidth="2" />
        <circle cx="250" cy="58" r="17" strokeWidth="0.8" />
        <path className="iv-stamp-check" d="M240 58l7 7 14-15" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

/** No.05 — The Expedition: a charted voyage to a flagged landfall, drawn on hover. */
function Expedition() {
  return (
    <svg viewBox="0 0 300 116" className="iv" fill="none" stroke="currentColor">
      {/* night sky over the route */}
      <g className="iv-stars" strokeWidth="1.3" strokeLinecap="round">
        <path d="M96 22v6M93 25h6" />
        <path d="M168 16v5M165.5 18.5h5" />
        <path d="M212 30v5M209.5 32.5h5" />
      </g>
      {/* the planned route, then the inked voyage */}
      <path className="iv-sea-od" d="M30 86 C 90 96 110 50 160 58 S 236 40 268 34" strokeWidth="1.4" stroke="currentColor" strokeDasharray="4 6" />
      <path className="iv-sea-line" d="M30 86 C 90 96 110 50 160 58 S 236 40 268 34" stroke={CREDIT} strokeWidth="2.4" strokeLinecap="round" />
      {/* the start, a waypoint, and the flagged landfall */}
      <circle cx="30" cy="86" r="3.4" fill="currentColor" stroke="none" />
      <circle className="iv-sea-node" cx="160" cy="58" r="4" fill="hsl(var(--gold))" stroke="hsl(var(--background))" strokeWidth="1.6" />
      <g stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M268 34v-22" />
        <path d="M268 12l16 5-16 6Z" fill={DEBIT} stroke={DEBIT} />
      </g>
    </svg>
  );
}

/** No.04 — Import Anything: a tangle that untangles into a clean register. */
function ImportAnything() {
  return (
    <svg viewBox="0 0 300 116" className="iv" fill="none" stroke="currentColor">
      <path
        className="iv-tangle"
        d="M22 58c14-30 30 26 44-4s-2-34 18-22 6 40 26 28 2-36 20-26"
        strokeWidth="2"
        strokeLinecap="round"
        stroke={DEBIT}
      />
      <path className="iv-arrow" d="M150 58h30m-9-7l9 7-9 7" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <g className="iv-rows" strokeWidth="2" strokeLinecap="round" stroke={CREDIT}>
        <line x1="196" y1="38" x2="284" y2="38" />
        <line x1="196" y1="58" x2="284" y2="58" />
        <line x1="196" y1="78" x2="262" y2="78" />
      </g>
    </svg>
  );
}

/** No.05 — Nightly Auditor: a moon, stars and a shield-check that draws. */
function Auditor() {
  return (
    <svg viewBox="0 0 300 116" className="iv" fill="none" stroke="currentColor">
      <path className="iv-moon" d="M52 22a20 20 0 1 0 16 32 16 16 0 0 1-16-32Z" strokeWidth="1.6" />
      <g className="iv-stars" strokeWidth="1.3" strokeLinecap="round">
        <path d="M104 30v6M101 33h6" />
        <path d="M150 18v5M147.5 20.5h5" />
        <path d="M120 54v5M117.5 56.5h5" />
      </g>
      <line className="iv-rule" x1="24" y1="92" x2="196" y2="92" strokeWidth="1" />
      <g className="iv-shield" stroke="currentColor">
        <path d="M250 26l-24 9v20c0 16 24 25 24 25s24-9 24-25V35Z" strokeWidth="2" />
        <path className="iv-audit-check" d="M238 56l8 8 16-17" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

/** No.06 — Tax, Filed Quietly: a form a "FILED" stamp slams down onto. */
function TaxFiled() {
  return (
    <svg viewBox="0 0 300 116" className="iv" fill="none" stroke="currentColor">
      <g className="iv-doc" strokeWidth="1.6" strokeLinecap="round">
        <rect x="92" y="12" width="116" height="92" rx="2" strokeWidth="2" />
        <line x1="104" y1="32" x2="196" y2="32" />
        <line x1="104" y1="48" x2="196" y2="48" />
        <line x1="104" y1="64" x2="170" y2="64" />
        <line x1="104" y1="80" x2="184" y2="80" />
      </g>
      <g className="iv-filed">
        <rect x="112" y="44" width="76" height="28" rx="2" strokeWidth="2.4" stroke={DEBIT} />
        <text x="150" y="63" textAnchor="middle" stroke="none" fill={DEBIT} fontFamily="'Spline Sans Mono', monospace" fontSize="14" fontWeight="700" letterSpacing="1.5">
          FILED
        </text>
      </g>
    </svg>
  );
}

const SCENES = [Clerk, ImportAnything, Subscriptions, Auditor, Expedition, TaxFiled];

export function PlateVisual({ index }: { index: number }) {
  const Scene = SCENES[index % SCENES.length];
  return <Scene />;
}
