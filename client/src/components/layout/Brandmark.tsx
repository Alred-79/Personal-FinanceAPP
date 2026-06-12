import { cn } from "@/lib/utils";

/**
 * The institution's seal: an engraved monogram in a double-ruled medallion,
 * the kind pressed onto banknotes and share certificates.
 */
export function Brandmark({
  size = 36,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={cn("shrink-0", className)}
      aria-hidden="true"
      focusable="false"
    >
      <circle
        cx="50"
        cy="50"
        r="46"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
      <circle
        cx="50"
        cy="50"
        r="40"
        fill="none"
        stroke="currentColor"
        strokeWidth="0.8"
      />
      {/* radiating engraver's rays */}
      {Array.from({ length: 36 }).map((_, i) => {
        const a = (i / 36) * Math.PI * 2;
        const r1 = 40;
        const r2 = i % 2 === 0 ? 45 : 43;
        return (
          <line
            key={i}
            x1={50 + r1 * Math.cos(a)}
            y1={50 + r1 * Math.sin(a)}
            x2={50 + r2 * Math.cos(a)}
            y2={50 + r2 * Math.sin(a)}
            stroke="currentColor"
            strokeWidth="0.7"
            opacity="0.7"
          />
        );
      })}
      {/* monogram L */}
      <text
        x="50"
        y="50"
        textAnchor="middle"
        dominantBaseline="central"
        fontFamily="Fraunces, Georgia, serif"
        fontSize="46"
        fontWeight="600"
        fill="currentColor"
      >
        £
      </text>
    </svg>
  );
}
