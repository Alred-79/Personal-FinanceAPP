import { cn } from "@/lib/utils";
import { NOTE, PLATES, VIEW } from "./specimenData";

/**
 * The engraved specimen note.
 *
 * One plate carrying the five documented features as engraving, not as icons:
 * the security thread runs the full height of the note (three filaments, one per
 * token family), the vault elevation has exactly two open doorways and a third
 * struck out, each surviving doorway carries a warded lock (a token cut for one
 * door will not turn in the other), the serial register is a block of
 * microprinted audit rows with a denial among them, and the failed impression is
 * a blank the press left — now stamped rather than silent.
 *
 * ② and ③ deliberately share the elevation, because the two mechanisms are about
 * the same object: ② is which doors exist at all (settled at build time by the
 * import guard, which is why its callout points at the lintel naming the
 * package), ③ is who may pass through one (settled at request time, which is why
 * its callout points at the lock itself).
 *
 * Leader lines and anchor rings live here too, in the same coordinate space as
 * the note, so a callout always points at the thing it names. The numbered discs
 * themselves are real HTML buttons layered on top (see SpecimenSheet) — an SVG
 * shape cannot carry a focus ring or a tab role honestly.
 *
 * Decorative throughout: everything it says is said in text by the callouts.
 */

const GOLD = "hsl(var(--gold))";
const DEBIT = "hsl(var(--debit))";

/** The real scope vocabulary, set as microprint along the note's lower edge. */
const SCOPE_MICROPRINT = [
  "read:accounts",
  "read:transactions",
  "read:budgets",
  "read:goals",
  "read:forecast",
  "read:networth",
  "read:subscriptions",
  "read:scenarios",
  "read:context",
].join("  ·  ");

/** The token families, microprinted down the three filaments of the thread. */
const FILAMENTS = ["session", "assistant_action", "mcp"];

/**
 * The two sanctioned database doors, drawn as an elevation. Their x positions
 * are shared by the doorway group (②) and the lock group (③) so the escutcheons
 * cannot drift off the doors they belong to.
 */
const DOORS = [
  { x: 390, label: "vault.py" },
  { x: 446, label: "actions.py" },
] as const;

/**
 * Rows shaped exactly like a real audit row — resource, decision, latency, a
 * truncated params fingerprint. The figures are illustrative and match the
 * Reading Room's example ledger; the denial is the row that matters.
 */
const REGISTER_ROWS: { serial: string; resource: string; decision: string; ms: string; hash: string }[] = [
  { serial: "00417", resource: "get_forecast", decision: "ALLOW", ms: "0.118", hash: "c740b8ae" },
  { serial: "00416", resource: "run_what_if", decision: "ALLOW", ms: "0.096", hash: "a3f0c7d1" },
  { serial: "00415", resource: "get_subscriptions", decision: "ALLOW", ms: "0.071", hash: "5b19e402" },
  { serial: "00414", resource: "budget://context", decision: "DENY", ms: "0.004", hash: "7e2b1f90" },
];

export function SpecimenNote({ active }: { active: number }) {
  return (
    <svg
      viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
      className="spx-note"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        {/* the hatch the failed impression is filled with */}
        <pattern id="spx-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(38)">
          <line x1="0" y1="0" x2="0" y2="7" stroke="currentColor" strokeWidth="0.7" opacity="0.5" />
        </pattern>
        {/* the note field clips the microprint that runs past its edge */}
        <clipPath id="spx-field">
          <rect x={NOTE.x} y={NOTE.y} width={NOTE.w} height={NOTE.h} />
        </clipPath>
        {/* the sheet's own box: the leader layer is clipped to it so no stroke
            can ever reach past the plate and into the reading below */}
        <clipPath id="spx-sheetbox">
          <rect x="0" y="0" width={VIEW.w} height={VIEW.h} />
        </clipPath>
      </defs>

      {/*
        THE ARTWORK, as one group.

        It is grouped rather than left loose so the plate can be taken OUT OF
        FOCUS as a whole while the leader layer below stays sharp — see
        `.spx-note__art` in landing.css. Opacity on a parent is multiplicative,
        so the active leader could not stay lit if the leaders lived in here.
      */}
      <g className="spx-note__art">
      {/* ── the plate edge ─────────────────────────────────────────────── */}
      <rect
        x={NOTE.x}
        y={NOTE.y}
        width={NOTE.w}
        height={NOTE.h}
        strokeWidth="1.8"
        opacity="0.75"
      />
      <rect
        x={NOTE.x + 9}
        y={NOTE.y + 9}
        width={NOTE.w - 18}
        height={NOTE.h - 18}
        strokeWidth="0.7"
        opacity="0.4"
      />
      {/* lathe-work: a fine ruled ground the whole note is printed over */}
      <g clipPath="url(#spx-field)" opacity="0.14" strokeWidth="0.6">
        {Array.from({ length: 22 }).map((_, i) => (
          <path
            key={i}
            d={`M${NOTE.x} ${NOTE.y + 14 + i * 15.4} Q ${NOTE.x + NOTE.w / 2} ${
              NOTE.y + 14 + i * 15.4 + (i % 2 ? 16 : -16)
            } ${NOTE.x + NOTE.w} ${NOTE.y + 14 + i * 15.4}`}
          />
        ))}
      </g>

      {/* corner ornaments — quarter rosettes, the note's engraved corners */}
      {(
        [
          [NOTE.x + 9, NOTE.y + 9, 1, 1],
          [NOTE.x + NOTE.w - 9, NOTE.y + 9, -1, 1],
          [NOTE.x + 9, NOTE.y + NOTE.h - 9, 1, -1],
          [NOTE.x + NOTE.w - 9, NOTE.y + NOTE.h - 9, -1, -1],
        ] as const
      ).map(([cx, cy, sx, sy], i) => {
        // The quarter arc must bulge INTO the note, which flips the sweep flag
        // on the two corners where the x and y directions disagree.
        const sweep = sx * sy > 0 ? 0 : 1;
        return (
          <g key={i} strokeWidth="0.8" opacity="0.55">
            <path d={`M${cx} ${cy + sy * 26} A 26 26 0 0 ${sweep} ${cx + sx * 26} ${cy}`} />
            <path d={`M${cx} ${cy + sy * 17} A 17 17 0 0 ${sweep} ${cx + sx * 17} ${cy}`} />
          </g>
        );
      })}

      {/* ── the portrait: the vignette a note is authenticated by ───────── */}
      <g>
        <ellipse cx="215" cy="235" rx="74" ry="96" strokeWidth="1.5" opacity="0.8" />
        <ellipse cx="215" cy="235" rx="64" ry="86" strokeWidth="0.6" opacity="0.45" />
        {/* a keyhole struck at the centre, radiating burin lines */}
        <g strokeWidth="0.7" opacity="0.4">
          {Array.from({ length: 36 }).map((_, i) => {
            const a = (i / 36) * Math.PI * 2;
            return (
              <line
                key={i}
                x1={215 + 30 * Math.cos(a)}
                y1={235 + 39 * Math.sin(a)}
                x2={215 + 58 * Math.cos(a)}
                y2={235 + 78 * Math.sin(a)}
              />
            );
          })}
        </g>
        <circle cx="215" cy="222" r="15" strokeWidth="1.8" stroke={GOLD} />
        <path d="M215 234 L208 262 h14 Z" strokeWidth="1.8" stroke={GOLD} />
        <text
          x="215"
          y="352"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          opacity="0.55"
          fontFamily="'Instrument Sans', sans-serif"
          fontSize="9"
          fontWeight="600"
          letterSpacing="2.6"
        >
          AGENT SURFACE
        </text>
        <line x1="152" y1="366" x2="278" y2="366" strokeWidth="0.7" opacity="0.4" />
        <text
          x="215"
          y="380"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          opacity="0.42"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="8"
        >
          countersigned · server/tests/
        </text>
      </g>

      {/* ── ① the security thread: three filaments, one per token family ──
          Woven into the paper rather than printed on it: each filament carries
          its own HKDF label, and they are set at different depths so the group
          reads as one thread and not as a rule down the middle of the note. */}
      <g className={cn("spx-thread", active === 1 && "is-on")}>
        {FILAMENTS.map((name, i) => {
          const x = [320, 331, 342][i];
          const labelY = NOTE.y + 96 + i * 88;
          return (
            <g key={name}>
              <line
                className="spx-thread__wire"
                x1={x}
                y1={NOTE.y + 4}
                x2={x}
                y2={NOTE.y + NOTE.h - 4}
                strokeWidth={i === 1 ? 2.2 : 1.1}
                stroke={GOLD}
                strokeDasharray={i === 1 ? "16 6" : i === 0 ? "7 9" : "11 7"}
                opacity={i === 1 ? 0.85 : 0.4}
              />
              {/* rotated a quarter turn about its own start point, so the
                  microprint reads down the filament it belongs to */}
              <text
                x={x}
                y={labelY}
                dy="-2.6"
                transform={`rotate(90 ${x} ${labelY})`}
                stroke="none"
                fill="currentColor"
                opacity="0.4"
                fontFamily="'Spline Sans Mono', monospace"
                fontSize="7"
                letterSpacing="0.2"
              >
                {`budget-ai/jwt/${name}`}
              </text>
            </g>
          );
        })}
      </g>

      {/* ── the issuing house: the note's own title block ────────────────── */}
      <g>
        <text
          x="478"
          y="122"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          opacity="0.82"
          fontFamily="Fraunces, Georgia, serif"
          fontSize="21"
          fontWeight="600"
          letterSpacing="1.4"
        >
          The Ledger
        </text>
        <line x1="398" y1="136" x2="558" y2="136" strokeWidth="0.8" opacity="0.45" />
        <line x1="418" y1="140" x2="538" y2="140" strokeWidth="0.5" opacity="0.3" />
        <text
          x="478"
          y="158"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          opacity="0.6"
          fontFamily="'Instrument Sans', sans-serif"
          fontSize="7.5"
          fontWeight="600"
          letterSpacing="2.4"
        >
          SPECIMEN OF SECURITY FEATURES
        </text>
        <text
          x="478"
          y="176"
          textAnchor="middle"
          stroke="none"
          fill={GOLD}
          opacity="0.7"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="8"
          letterSpacing="1"
        >
          model context protocol · surface
        </text>
      </g>

      {/* ── ② the elevation: two doorways admitted, a third struck out ──── */}
      <g>
        <line x1="378" y1="342" x2="574" y2="342" strokeWidth="1.6" opacity="0.8" />
        <line x1="378" y1="347" x2="574" y2="347" strokeWidth="0.6" opacity="0.4" />
        {/* the lintel */}
        <line x1="386" y1="276" x2="566" y2="276" strokeWidth="1.2" opacity="0.7" />
        <text
          x="476"
          y="269"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          opacity="0.55"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="8"
          letterSpacing="1"
        >
          server/src/mcp/
        </text>
        {/* the two sanctioned doors, each named on its own threshold */}
        {DOORS.map((d) => (
          <g key={d.label}>
            <path d={`M${d.x} 342 V 308 a 22 22 0 0 1 44 0 V 342`} strokeWidth="1.6" opacity="0.9" />
            <path
              d={`M${d.x + 7} 342 V 310 a 15 15 0 0 1 30 0 V 342`}
              strokeWidth="0.6"
              opacity="0.42"
            />
            <text
              x={d.x + 22}
              y="361"
              textAnchor="middle"
              stroke="none"
              fill="currentColor"
              opacity="0.5"
              fontFamily="'Spline Sans Mono', monospace"
              fontSize="7"
            >
              {d.label}
            </text>
          </g>
        ))}
        {/* the third door: refused before it exists */}
        <g opacity="0.68">
          <path
            d="M502 342 V 308 a 22 22 0 0 1 44 0 V 342"
            strokeWidth="1.3"
            strokeDasharray="4 4"
            stroke={DEBIT}
          />
          <path d="M509 310 L539 336 M539 310 L509 336" strokeWidth="1.6" stroke={DEBIT} />
        </g>
        <text
          x="476"
          y="376"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          opacity="0.42"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="6.8"
          letterSpacing="0.4"
        >
          a third door fails the build
        </text>
      </g>

      {/* ── ③ the ward: each surviving door is locked, and keyed separately ──
          The struck-out door deliberately gets none — it never opens, so it
          never needs one. The escutcheon on actions.py is drawn a little larger
          than the callout's own anchor ring, so when ③ is selected the ring
          lands INSIDE the lock plate and the keyhole reads as its pin: the
          callout does not point at the lock so much as turn in it. */}
      <g className={cn("spx-locks", active === 3 && "is-on")}>
        {DOORS.map((d) => {
          const cx = d.x + 22;
          return (
            <g key={d.label}>
              <ellipse cx={cx} cy="320" rx="11" ry="13" stroke={GOLD} strokeWidth="1.3" />
              <ellipse
                cx={cx}
                cy="320"
                rx="7.4"
                ry="9.4"
                stroke={GOLD}
                strokeWidth="0.5"
                opacity="0.55"
              />
              {/* the keyway: a bore and the ward slot cut down from it */}
              <circle cx={cx} cy="316" r="2.4" stroke={GOLD} strokeWidth="1" />
              <path
                d={`M${cx - 2.1} 326 L${cx - 0.9} 318 h1.8 L${cx + 2.1} 326 Z`}
                fill={GOLD}
                stroke="none"
                opacity="0.75"
              />
            </g>
          );
        })}
        {/* Set at 251, not 256: at 256 this line's descenders closed to ~3 plate
            units of the lintel's own label, which reads as one cramped block
            rather than two engraved lines. */}
        <text
          x="476"
          y="251"
          textAnchor="middle"
          stroke="none"
          fill={GOLD}
          opacity="0.62"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="7"
          letterSpacing="0.4"
        >
          one token · one door
        </text>
      </g>

      {/* ── ④ the serial register: microprinted audit rows, one a denial ── */}
      <g className={cn("spx-register-block", active === 4 && "is-on")}>
        <rect x="588" y="96" width="272" height="80" strokeWidth="0.8" opacity="0.45" />
        <text
          x="590"
          y="90"
          stroke="none"
          fill="currentColor"
          opacity="0.55"
          fontFamily="'Instrument Sans', sans-serif"
          fontSize="7.5"
          fontWeight="600"
          letterSpacing="2.2"
        >
          REGISTER OF ACCESS
        </text>
        <text
          x="860"
          y="90"
          textAnchor="end"
          stroke="none"
          fill={GOLD}
          opacity="0.9"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="8"
          letterSpacing="0.8"
        >
          APPEND ONLY
        </text>
        {REGISTER_ROWS.map((r, i) => {
          const y = 114 + i * 16;
          const deny = r.decision === "DENY";
          return (
            <g key={r.serial}>
              <line x1="596" y1={y + 4} x2="852" y2={y + 4} strokeWidth="0.5" opacity="0.2" />
              <text
                stroke="none"
                fontFamily="'Spline Sans Mono', monospace"
                fontSize="8"
                fill="currentColor"
                opacity="0.72"
              >
                <tspan x="596" y={y}>{r.serial}</tspan>
                <tspan x="630" y={y}>{r.resource}</tspan>
                <tspan x="730" y={y} fill={deny ? DEBIT : "currentColor"} opacity={deny ? 1 : 0.72}>
                  {r.decision}
                </tspan>
                <tspan x="772" y={y}>{r.ms}</tspan>
                <tspan x="806" y={y}>{r.hash}</tspan>
              </text>
            </g>
          );
        })}
      </g>

      {/* ── ⑤ the blank the press left — now stamped, not silent ────────── */}
      <g className={cn("spx-blank", active === 5 && "is-on")}>
        <rect
          x="608"
          y="242"
          width="256"
          height="118"
          strokeWidth="0.9"
          strokeDasharray="6 5"
          opacity="0.5"
        />
        <rect x="608" y="242" width="256" height="118" fill="url(#spx-hatch)" stroke="none" opacity="0.35" />
        <g transform="rotate(-7 736 300)" opacity="0.78">
          <rect x="668" y="288" width="136" height="26" strokeWidth="1.4" stroke={DEBIT} />
          <text
            x="736"
            y="305"
            textAnchor="middle"
            stroke="none"
            fill={DEBIT}
            fontFamily="'Spline Sans Mono', monospace"
            fontSize="10.5"
            fontWeight="700"
            letterSpacing="1.4"
          >
            DISCARD LOGGED
          </text>
        </g>
        <text
          x="736"
          y="348"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          opacity="0.45"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="7.5"
        >
          the impression that failed, and said so
        </text>
      </g>

      {/* ── microprint along the lower edge: the real scope vocabulary ──── */}
      <g clipPath="url(#spx-field)">
        <text
          x={NOTE.x + 14}
          y={NOTE.y + NOTE.h - 16}
          stroke="none"
          fill="currentColor"
          opacity="0.3"
          fontFamily="'Spline Sans Mono', monospace"
          fontSize="6.5"
          letterSpacing="0.2"
        >
          {`${SCOPE_MICROPRINT}  ·  ${SCOPE_MICROPRINT}`}
        </text>
      </g>

      {/* ── the overprint every specimen carries ────────────────────────── */}
      {/* x is nudged by half the letter-spacing: a middle-anchored run counts
          the trailing space, which would otherwise sit the word left of centre */}
      <text
        x="511"
        y="248"
        textAnchor="middle"
        transform="rotate(-9 505 248)"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.13"
        fontFamily="Fraunces, Georgia, serif"
        fontSize="66"
        fontWeight="600"
        letterSpacing="12"
      >
        SPECIMEN
      </text>
      </g>

      {/* ── leader lines + anchor rings ───────────────────────────────────
          Outside .spx-note__art on purpose: when the plate goes out of focus
          the ACTIVE leader has to stay sharp and lit, tying its numbered disc
          to the reading. Clipped to the sheet box so it cannot reach past it. */}
      <g clipPath="url(#spx-sheetbox)">
      {PLATES.map((p) => {
        const [ax, ay] = p.anchor;
        const [mx, my] = p.marker;
        const dx = ax - mx;
        const dy = ay - my;
        const len = Math.hypot(dx, dy) || 1;
        const on = active === p.n;
        return (
          <g key={p.n} className={cn("spx-leader", on && "is-on")}>
            <line
              className="spx-leader__line"
              x1={mx + (dx / len) * 27}
              y1={my + (dy / len) * 27}
              x2={ax - (dx / len) * 10}
              y2={ay - (dy / len) * 10}
              strokeWidth={on ? 1.6 : 1}
              strokeDasharray="5 5"
            />
            <circle cx={ax} cy={ay} r={on ? 8.5 : 5.5} strokeWidth={on ? 1.8 : 1.1} />
            <circle cx={ax} cy={ay} r="1.9" fill="currentColor" stroke="none" />
            {/* The key the note keeps once the callouts move off the plate. It
                has to survive the note being rendered a third of its desktop
                size, so it is struck as a legible token rather than a hairline
                numeral, set back along the leader's own bearing. */}
            <g className="spx-leader__n">
              <circle
                cx={ax + (dx / len) * 26}
                cy={ay + (dy / len) * 26}
                r="17"
                fill="hsl(var(--card))"
                strokeWidth="1.4"
              />
              <text
                x={ax + (dx / len) * 26}
                y={ay + (dy / len) * 26 + 8}
                textAnchor="middle"
                stroke="none"
                fill="currentColor"
                fontFamily="'Spline Sans Mono', monospace"
                fontSize="22"
                fontWeight="700"
              >
                {p.n}
              </text>
            </g>
          </g>
        );
      })}
      </g>
    </svg>
  );
}
