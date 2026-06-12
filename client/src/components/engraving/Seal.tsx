import { cn } from "@/lib/utils";

interface SealProps {
  /** Text engraved around the top arc of the seal. */
  label?: string;
  size?: number;
  /** "wax" = embossed gold medallion; "approved" = green; "void" = debit. */
  tone?: "wax" | "approved" | "void";
  className?: string;
  /** Gentle pulse to draw the eye to a freshly-earned seal. */
  pulse?: boolean;
}

const TONES = {
  wax: "text-gold",
  approved: "text-credit",
  void: "text-debit",
};

/**
 * A pressed seal / medallion. Curved text rides the upper arc, a star sits at
 * the centre, and a ring of teeth gives it the milled edge of a coin.
 */
export function Seal({
  label = "Certified · Paid · Certified · Paid",
  size = 88,
  tone = "wax",
  className,
  pulse = false,
}: SealProps) {
  const pathId = `seal-arc-${label.replace(/[^a-z0-9]/gi, "").slice(0, 12)}-${size}`;
  return (
    <div
      className={cn("grid place-items-center rounded-full", pulse && "[animation:seal-pulse_2.6s_ease-in-out_infinite]", className)}
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 100 100" width={size} height={size} className={TONES[tone]} aria-hidden="true">
        <defs>
          <path id={pathId} d="M 50,50 m -38,0 a 38,38 0 1,1 76,0 a 38,38 0 1,1 -76,0" />
        </defs>
        {/* milled edge */}
        {Array.from({ length: 60 }).map((_, i) => {
          const a = (i / 60) * Math.PI * 2;
          return (
            <line
              key={i}
              x1={50 + 46 * Math.cos(a)}
              y1={50 + 46 * Math.sin(a)}
              x2={50 + 49 * Math.cos(a)}
              y2={50 + 49 * Math.sin(a)}
              stroke="currentColor"
              strokeWidth="1.1"
              opacity="0.85"
            />
          );
        })}
        <circle cx="50" cy="50" r="44" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="50" cy="50" r="33" fill="none" stroke="currentColor" strokeWidth="0.7" opacity="0.6" />
        <text fontSize="7.2" fontWeight="600" letterSpacing="0.5" fill="currentColor" fontFamily="'Instrument Sans', sans-serif">
          <textPath href={`#${pathId}`} startOffset="2%">
            {label.toUpperCase()}
          </textPath>
        </text>
        {/* central star */}
        <g transform="translate(50,54)">
          {Array.from({ length: 5 }).map((_, i) => {
            const a = (i / 5) * Math.PI * 2 - Math.PI / 2;
            const a2 = a + Math.PI / 5;
            const R = 10;
            const r = 4;
            const x1 = R * Math.cos(a);
            const y1 = R * Math.sin(a);
            const x2 = r * Math.cos(a2);
            const y2 = r * Math.sin(a2);
            return <polygon key={i} points={`0,0 ${x1},${y1} ${x2},${y2}`} fill="currentColor" opacity="0.9" />;
          })}
        </g>
      </svg>
    </div>
  );
}
