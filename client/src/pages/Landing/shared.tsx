import { ReactNode, useEffect, useState } from "react";
import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { landingScrollTo } from "./hooks/useLenis";

/** The landing's house easing — a strong quint-out, matching the app's --ease-out. */
export const EASE = [0.22, 1, 0.36, 1] as const;

/** A scroll-triggered rise — reveals as the section enters the viewport. */
export function Rise({
  children,
  className,
  delay = 0,
  y = 26,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.75, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  );
}

/** The institution's wax seal — a gold medallion with the £ monogram. */
export function LedgerSeal({ size = 34, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-display font-semibold text-[hsl(46_52%_96%)]",
        className
      )}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.5,
        background:
          "radial-gradient(circle at 38% 32%, hsl(var(--gold)), hsl(42 56% 26%))",
        boxShadow:
          "inset 0 0 0 2px hsl(46 52% 96% / 0.3), 0 2px 8px hsl(167 30% 12% / 0.3)",
      }}
      aria-hidden
    >
      £
    </span>
  );
}

/** A live "accruing today" ticker — a tiny credit figure that climbs. */
export function AccrualTicker() {
  const reduce = useReducedMotion();
  const [v, setV] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const id = setInterval(() => setV((x) => x + 0.0007 + Math.random() * 0.0006), 120);
    return () => clearInterval(id);
  }, [reduce]);
  return <span className="figure ink-credit">+${v.toFixed(4)}</span>;
}

/** A bordered SVG glyph for a feature card. */
export function FeatureIcon({ children }: { children: ReactNode }) {
  return (
    <span className="mb-4 grid h-11 w-11 place-items-center border border-rule-strong/50 text-gold">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
        {children}
      </svg>
    </span>
  );
}

/** In-page anchor link that smooth-scrolls via Lenis (with a fixed-nav offset)
 *  and updates the hash, instead of the browser's hard jump under a fixed nav. */
export function AnchorLink({
  to,
  className,
  children,
}: {
  to: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a
      href={to}
      className={className}
      onClick={(e) => {
        e.preventDefault();
        landingScrollTo(to);
        if (history.replaceState) history.replaceState(null, "", to);
      }}
    >
      {children}
    </a>
  );
}
