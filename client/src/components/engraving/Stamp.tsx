import { ReactNode, useId } from "react";
import { cn } from "@/lib/utils";

type StampVariant = "debit" | "credit" | "gold" | "ink";

const VARIANT_CLASSES: Record<StampVariant, string> = {
  debit: "text-debit border-debit",
  credit: "text-credit border-credit",
  gold: "text-gold border-gold",
  ink: "text-foreground border-foreground",
};

interface StampProps {
  children: ReactNode;
  variant?: StampVariant;
  /** Skip the slam-down entrance (e.g. inside lists that already stagger). */
  still?: boolean;
  className?: string;
}

/**
 * A rubber stamp pressed onto the page: double border, rotated, with an
 * feTurbulence displacement so the ink edge is convincingly rough.
 */
export function Stamp({
  children,
  variant = "debit",
  still = false,
  className,
}: StampProps) {
  const rawId = useId();
  const filterId = `stamp-${rawId.replace(/[^a-zA-Z0-9_-]/g, "")}`;

  return (
    <span
      className={cn(
        "relative inline-block select-none",
        !still && "animate-stamp-in",
        still && "-rotate-8",
        className
      )}
      style={still ? { transform: "rotate(-8deg)" } : undefined}
    >
      <svg width="0" height="0" className="absolute" aria-hidden="true">
        <filter id={filterId}>
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.13"
            numOctaves="2"
            result="n"
            seed="7"
          />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="2.2" />
        </filter>
      </svg>
      <span
        className={cn(
          "inline-block border-2 px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-[0.22em]",
          "opacity-90 mix-blend-multiply dark:mix-blend-screen",
          VARIANT_CLASSES[variant]
        )}
        style={{
          filter: `url(#${filterId})`,
          boxShadow: "inset 0 0 0 1px currentColor",
        }}
      >
        {children}
      </span>
    </span>
  );
}
