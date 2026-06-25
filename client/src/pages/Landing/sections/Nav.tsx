import { useState } from "react";
import { Link } from "react-router-dom";
import { useMotionValueEvent, useScroll } from "motion/react";
import { cn } from "@/lib/utils";
import { AnchorLink, LedgerSeal } from "../shared";

/** Top register / nav — shrinks once the page scrolls past the hero crest. */
export function Nav() {
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
      <div className="flex items-center gap-2.5">
        <LedgerSeal size={shrunk ? 30 : 34} className="transition-all duration-300" />
        <b className="whitespace-nowrap font-display text-[1.05rem] font-semibold tracking-tight">The Ledger</b>
      </div>
      <div className="flex items-center gap-5 sm:gap-7">
        <AnchorLink to="#features" className="hidden text-[0.82rem] text-muted-foreground transition-colors hover:text-foreground sm:inline">
          Instruments
        </AnchorLink>
        <AnchorLink to="#how" className="hidden text-[0.82rem] text-muted-foreground transition-colors hover:text-foreground sm:inline">
          How it works
        </AnchorLink>
        <AnchorLink to="#vault" className="hidden text-[0.82rem] text-muted-foreground transition-colors hover:text-foreground sm:inline">
          The Vault
        </AnchorLink>
        <Link
          to="/login"
          className="press hidden border border-rule-strong/60 px-3.5 py-2 text-[0.8rem] font-semibold uppercase tracking-[0.04em] sm:inline-block"
        >
          Sign in
        </Link>
        <Link
          to="/login"
          className="press bg-primary px-3.5 py-2 text-[0.8rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground"
        >
          Open an account
        </Link>
      </div>
    </nav>
  );
}
