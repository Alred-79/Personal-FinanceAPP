/**
 * Bespoke engraved "specimen" scenes for each vault guarantee — the picture that
 * fills each safe-deposit box. Each idles subtly and performs a strong, legible
 * flourish on box hover (the animations live in landing.css, keyed off
 * `.vault-box:hover .ss-*`). Stroke = currentColor (the stage is tinted gold);
 * credit/debit inks are set directly so the colour law still reads.
 */

const GOLD = "hsl(var(--gold))";
const DEBIT = "hsl(var(--debit))";
const CREDIT = "hsl(var(--credit))";

/** No.01 — Read-only: a watchful eye that blinks and scans the ledger. */
function ReadOnly() {
  return (
    <svg viewBox="0 0 300 100" className="ss" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <g className="ss-eye-ticks" strokeWidth="2" opacity="0.45">
        <path d="M150 16v-9M150 93v-9M86 50h-9M223 50h9" />
        <path d="M107 25l-6-6M193 25l6-6M107 75l-6 6M193 75l6 6" />
      </g>
      <g className="ss-eye">
        <path d="M104 50c18-27 74-27 92 0-18 27-74 27-92 0Z" strokeWidth="2.6" />
        <circle className="ss-iris" cx="150" cy="50" r="13" strokeWidth="2.3" />
        <circle cx="150" cy="50" r="4.5" fill="currentColor" stroke="none" />
      </g>
      <circle className="ss-glint" cx="145" cy="45" r="2.2" fill={GOLD} stroke="none" />
    </svg>
  );
}

/** No.02 — Propose / stamp: an approval stamp slams down and seals a check. */
function StampScene() {
  return (
    <svg viewBox="0 0 300 100" className="ss" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <rect x="92" y="44" width="116" height="44" rx="2" strokeWidth="2" opacity="0.85" />
      <line x1="104" y1="58" x2="168" y2="58" strokeWidth="2.2" stroke={CREDIT} />
      <line x1="104" y1="70" x2="150" y2="70" strokeWidth="2.2" stroke={DEBIT} />
      <circle className="ss-ring" cx="150" cy="54" r="20" strokeWidth="2" stroke={GOLD} opacity="0" />
      <g className="ss-stamp">
        <rect x="138" y="6" width="24" height="9" rx="2" strokeWidth="2.2" />
        <rect x="130" y="15" width="40" height="9" rx="1.5" strokeWidth="2.2" />
        <path d="M133 24h34" strokeWidth="2.2" />
      </g>
      <g className="ss-seal" opacity="0">
        <circle cx="150" cy="54" r="14" strokeWidth="2.2" stroke={GOLD} />
        <path className="ss-seal-check" d="M143 54l5 5 9-11" strokeWidth="2.6" stroke={GOLD} />
      </g>
    </svg>
  );
}

/** No.03 — Scrubber: raw details get blacked out before they leave. */
function Redact() {
  const rows = [
    { y: 30, marks: "M96 30h12M114 30h22M140 30h30" },
    { y: 50, marks: "M96 50h36M138 50h10M152 50h34" },
    { y: 70, marks: "M96 70h16M118 70h16M140 70h16M162 70h22" },
  ];
  return (
    <svg viewBox="0 0 300 100" className="ss" fill="none" stroke="currentColor" strokeLinecap="round">
      {/* the raw data underneath */}
      <g strokeWidth="3" opacity="0.5">
        {rows.map((r) => (
          <path key={r.y} d={r.marks} />
        ))}
      </g>
      {/* a filter membrane the data is pushed through */}
      <line x1="206" y1="14" x2="206" y2="86" strokeWidth="1.6" strokeDasharray="3 4" stroke={GOLD} opacity="0.7" />
      {/* the redaction bars that wipe across on hover */}
      <g fill={DEBIT} stroke="none">
        <rect className="ss-redact ss-redact-1" x="94" y="24" width="100" height="12" rx="2.5" />
        <rect className="ss-redact ss-redact-2" x="94" y="44" width="100" height="12" rx="2.5" />
        <rect className="ss-redact ss-redact-3" x="94" y="64" width="100" height="12" rx="2.5" />
      </g>
    </svg>
  );
}

/** No.04 — Whole cents: a struck coin that flips and lands exact. */
function CentsCoin() {
  return (
    <svg viewBox="0 0 100 100" className="ss ss-coin" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="50" cy="50" r="33" strokeWidth="2.6" />
      <circle cx="50" cy="50" r="27" strokeWidth="1" strokeDasharray="1.4 3.4" opacity="0.7" />
      {/* a struck "$" */}
      <path d="M50 32v36" strokeWidth="2.4" />
      <path d="M58 39a8 8 0 0 0-8-5 7 7 0 0 0 0 14 7 7 0 0 1 0 14 8 8 0 0 1-8-5" strokeWidth="2.4" />
    </svg>
  );
}

/** No.05 — Stolen tokens self-destruct: a reused key cracks and shatters. */
function TokenShatter() {
  return (
    <svg viewBox="0 0 300 100" className="ss" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <circle className="ss-flash" cx="124" cy="50" r="22" strokeWidth="2" stroke={GOLD} opacity="0" />
      <g className="ss-key">
        <circle cx="124" cy="50" r="17" strokeWidth="2.6" />
        <circle cx="124" cy="50" r="6.5" strokeWidth="2.2" />
        <path d="M141 50h45M172 50v13M186 50v17" strokeWidth="2.6" />
      </g>
      <path className="ss-crack" d="M124 33l7 13-10 8 8 11" strokeWidth="2" stroke={DEBIT} opacity="0" />
      <g strokeWidth="2" stroke={GOLD} strokeLinecap="round">
        <path className="ss-shard ss-shard-a" d="M124 30l5 7" />
        <path className="ss-shard ss-shard-b" d="M140 44l8-3" />
        <path className="ss-shard ss-shard-c" d="M112 60l-7 5" />
        <path className="ss-shard ss-shard-d" d="M132 66l5 7" />
      </g>
    </svg>
  );
}

/** No.06 — Never sell your data: a price tag swings in and is voided. */
function NoSell() {
  return (
    <svg viewBox="0 0 300 100" className="ss" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <g className="ss-tag">
        <path d="M118 32h54a6 6 0 0 1 6 6v24a6 6 0 0 1-6 6h-54l-22-18Z" strokeWidth="2.4" />
        <circle cx="130" cy="50" r="3.6" strokeWidth="2" />
        <path d="M150 42v16M156 46a5 5 0 0 0-6-3 4 4 0 0 0 0 8 4 4 0 0 1 0 8 5 5 0 0 1-6-3" strokeWidth="2" />
      </g>
      <g className="ss-void" opacity="0">
        <circle cx="150" cy="50" r="30" strokeWidth="3.2" stroke={DEBIT} />
        <line x1="129" y1="29" x2="171" y2="71" strokeWidth="3.2" stroke={DEBIT} />
      </g>
    </svg>
  );
}

const SCENES = [ReadOnly, StampScene, Redact, CentsCoin, TokenShatter, NoSell];

export function SecurityScene({ index }: { index: number }) {
  const Scene = SCENES[index % SCENES.length];
  return <Scene />;
}
