/**
 * Engraved "specimen" scenes for the Cabinet — the product's reward/game layer.
 * Each is a small tactile emblem that idles quietly and performs a strong
 * flourish on card hover (animations in landing.css, keyed off `.cab-card:hover`).
 * All three are real surfaces: Goals (minted coins), Debts (the Bestiary), and
 * Campaigns (quarterly arcs). Stroke = currentColor (gold); credit/debit explicit.
 */

const GOLD = "hsl(var(--gold))";
const DEBIT = "hsl(var(--debit))";

const STAR = "M0 -7 L1.9 -2.2 L7 -1.8 L3 1.5 L4.3 6.8 L0 3.9 L-4.3 6.8 L-3 1.5 L-7 -1.8 L-1.9 -2.2 Z";

/** Goals Cabinet — a case of struck specimens; an empty slot mints on hover. */
function GoalsCabinet() {
  const slots = [44, 86, 128];
  return (
    <svg viewBox="0 0 220 100" className="cab" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <rect x="20" y="20" width="180" height="56" rx="3" strokeWidth="2" />
      <line x1="20" y1="66" x2="200" y2="66" strokeWidth="1.3" opacity="0.45" />
      {slots.map((cx, i) => (
        <g key={cx} className={`cab-coin cab-coin-${i + 1}`}>
          <circle cx={cx} cy="44" r="14" strokeWidth="2" />
          <circle cx={cx} cy="44" r="10.5" strokeWidth="0.8" opacity="0.5" />
          <path transform={`translate(${cx} 44) scale(0.85)`} d={STAR} fill={GOLD} stroke="none" />
        </g>
      ))}
      {/* the empty slot + the coin that mints into it */}
      <circle className="cab-slot" cx="170" cy="44" r="14" strokeWidth="1.5" strokeDasharray="3 3" opacity="0.5" />
      <g className="cab-mint">
        <circle cx="170" cy="44" r="14" strokeWidth="2" />
        <path transform="translate(170 44) scale(0.85)" d={STAR} fill={GOLD} stroke="none" />
      </g>
    </svg>
  );
}

/** The Bestiary — a debt-beast whose balance bar drains until it's FELLED. */
function Bestiary() {
  return (
    <svg viewBox="0 0 220 100" className="cab" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <g className="cab-beast">
        {/* horns */}
        <path d="M92 24 L83 8 M128 24 L137 8" strokeWidth="2.4" />
        {/* head */}
        <path d="M88 26 q22 -14 44 0 q11 14 -2 27 q-20 15 -40 0 q-13 -13 -2 -27 Z" strokeWidth="2.4" />
        {/* eyes + fangs */}
        <path d="M99 36 l7 4 M121 36 l-7 4" strokeWidth="2.2" />
        <path d="M104 54 l2 7 M116 54 l-2 7" strokeWidth="2" />
      </g>
      {/* balance bar that drains away */}
      <rect x="48" y="76" width="124" height="9" rx="4.5" strokeWidth="1.5" />
      <rect className="cab-bar-fill" x="50.5" y="78.5" width="119" height="4" rx="2" fill={DEBIT} stroke="none" />
      {/* the FELLED stamp */}
      <g className="cab-felled">
        <rect x="76" y="30" width="68" height="22" rx="2" strokeWidth="2.4" stroke={DEBIT} />
        <text x="110" y="45.5" textAnchor="middle" stroke="none" fill={DEBIT} fontFamily="'Spline Sans Mono', monospace" fontSize="12" fontWeight="700" letterSpacing="2">
          FELLED
        </text>
      </g>
    </svg>
  );
}

/** Campaigns — a quarter's arc that closes and a medal that seals it. */
function Campaigns() {
  return (
    <svg viewBox="0 0 220 100" className="cab" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="110" cy="44" r="30" strokeWidth="2.4" opacity="0.25" />
      <circle
        className="cab-arc"
        cx="110"
        cy="44"
        r="30"
        strokeWidth="2.8"
        stroke={GOLD}
        pathLength={100}
        strokeDasharray="100"
        strokeDashoffset="100"
        transform="rotate(-90 110 44)"
      />
      <g className="cab-medal">
        <circle cx="110" cy="44" r="17" strokeWidth="2" />
        <path transform="translate(110 44) scale(1.4)" d={STAR} fill={GOLD} stroke="none" />
      </g>
      {/* ribbon tails */}
      <path d="M101 60 L96 82 L105 75 L110 84 L115 75 L124 82 L119 60" strokeWidth="2" stroke={DEBIT} />
    </svg>
  );
}

const SCENES = [GoalsCabinet, Bestiary, Campaigns];

export function CabinetScene({ index }: { index: number }) {
  const Scene = SCENES[index % SCENES.length];
  return <Scene />;
}
