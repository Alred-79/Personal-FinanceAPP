import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { CornerRosette } from "./Guilloche";

interface CertificateProps {
  children: ReactNode;
  /** Seed so each certificate's corner engraving differs but stays stable. */
  seed?: number;
  /** Accent rule colour, e.g. a category tint. */
  accent?: string;
  className?: string;
  onClick?: () => void;
}

/**
 * A share-certificate plate: heavy double frame, an engraved rosette tucked
 * into each corner, and a fine accent rule along the top. Used for budget
 * envelopes and savings goals.
 */
export function Certificate({
  children,
  seed = 1,
  accent,
  className,
  onClick,
}: CertificateProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "plate group relative overflow-hidden bg-card transition-transform duration-300",
        onClick && "cursor-pointer hover:-translate-y-0.5",
        className
      )}
    >
      {/* accent rule */}
      {accent && (
        <div className="absolute inset-x-0 top-0 h-[3px]" style={{ background: accent }} />
      )}
      {/* corner rosettes */}
      <div className="pointer-events-none absolute -left-4 -top-4 text-gold/20">
        <CornerRosette size={64} seed={seed} />
      </div>
      <div className="pointer-events-none absolute -bottom-5 -right-5 text-gold/15">
        <CornerRosette size={80} seed={seed + 100} />
      </div>
      <div className="relative">{children}</div>
    </div>
  );
}
