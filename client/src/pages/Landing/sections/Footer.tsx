import { LedgerSeal } from "../shared";

/** Footer colophon. */
export function Footer() {
  return (
    <footer className="mt-20 border-t border-rule-strong/40 py-10">
      <div className="mx-auto flex max-w-[1080px] flex-wrap items-center justify-between gap-4 px-4 sm:px-8">
        <div className="flex items-center gap-2">
          <LedgerSeal size={28} />
          <b className="font-display text-[0.9rem] font-semibold">The Ledger</b>
        </div>
        <div className="flex gap-6">
          {["Privacy", "Security", "Terms", "Contact"].map((l) => (
            <span key={l} className="cursor-default text-[0.78rem] text-muted-foreground transition-colors hover:text-foreground">
              {l}
            </span>
          ))}
        </div>
        <p className="serial font-mono text-[0.7rem] tracking-[0.18em] text-muted-foreground">No. LK-42018</p>
      </div>
    </footer>
  );
}
