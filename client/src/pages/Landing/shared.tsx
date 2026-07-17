import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { landingScrollTo } from "./hooks/useLenis";

/** The landing's house easing — a strong quint-out, matching the app's --ease-out. */
export const EASE = [0.22, 1, 0.36, 1] as const;

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
