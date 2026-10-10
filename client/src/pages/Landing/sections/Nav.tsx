import { useState } from "react";
import { Link } from "react-router-dom";
import { useMotionValueEvent, useScroll } from "motion/react";
import { cn } from "@/lib/utils";
import { AnchorLink, LedgerSeal } from "../shared";
import { DemoLink } from "../demo";

const quiet = "hidden text-[0.82rem] text-muted-foreground transition-colors hover:text-foreground md:inline";

/** Top register / nav — shrinks once the page scrolls past the hero crest.
 *  `home` carries the in-page anchors; `subpage` (How it's built) links back. */
export function Nav({ variant = "home" }: { variant?: "home" | "subpage" }) {
  const { scrollY } = useScroll();
  const [shrunk, setShrunk] = useState(false);
  useMotionValueEvent(scrollY, "change", (y) => setShrunk(y > 40));

  return (
    <nav
      className={cn(
        "fixed inset-x-0 top-0 z-40 flex items-center justify-between border-b border-rule-strong/35 bg-background/80 px-4 backdrop-blur transition-[padding] duration-300 sm:px-8",
        shrunk ? "py-2" : "py-3.5"
      )}
    >
      <Link to="/welcome" className="flex items-center gap-2.5">
        <LedgerSeal size={shrunk ? 30 : 34} className="transition-all duration-300" />
        <b className="whitespace-nowrap font-display text-[1.05rem] font-semibold tracking-tight">The Ledger</b>
      </Link>
      <div className="flex items-center gap-5 sm:gap-7">
        {variant === "home" ? (
          <>
            <AnchorLink to="#forecast" className={quiet}>
              How it works
            </AnchorLink>
            <AnchorLink to="#features" className={quiet}>
              Features
            </AnchorLink>
            <AnchorLink to="#vault" className={quiet}>
              Trust
            </AnchorLink>
            <Link to="/how-its-built" className={quiet}>
              For engineers
            </Link>
          </>
        ) : (
          <Link to="/welcome" className={quiet}>
            &larr; Back to the overview
          </Link>
        )}
        <Link
          to="/login"
          className="press hidden border border-rule-strong/60 px-3.5 py-2 text-[0.8rem] font-semibold uppercase tracking-[0.04em] sm:inline-block"
        >
          Sign in
        </Link>
        <DemoLink className="press bg-primary px-3.5 py-2 text-[0.8rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground">
          Try the demo
        </DemoLink>
      </div>
    </nav>
  );
}
