import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * A persistent, quiet indicator placed wherever bank data appears: a stamped
 * "read-only" assurance that the connection can see, not move. One tap opens a
 * plain-language explainer. This turns the app's most-distrusted surface (a
 * money app touching your bank) into a stated strength.
 *
 * Engraver's-Ledger idiom: rounded-none, mono smallcaps, gold reserved for the
 * lock glyph (chrome), never for a money figure. See docs/FRONTEND-REPOSITIONING.
 */
export function ReadOnlyBadge({
  className,
  label = "Read-only · we can see, not move",
}: {
  className?: string;
  /** Override the chip copy for tighter spots (defaults to the full assurance). */
  label?: string;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "press inline-flex items-center gap-1.5 rounded-none border border-rule-strong/45 bg-card/70 px-2.5 py-1",
            "font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground",
            "transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
          aria-label="How the bank connection works — read-only by default"
        >
          <LockGlyph />
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[19rem] rounded-none border-rule-strong/50 p-4" align="start">
        <p className="dept-label mb-1.5">The connection · Read-only</p>
        <p className="text-[0.8rem] leading-relaxed text-foreground">
          When you link an account, the vault opens <strong>read-only</strong> — a
          read literally can&rsquo;t write. We can see your transactions to do the
          math; we can&rsquo;t move a dollar or see full account numbers.
        </p>
        <p className="mt-2 text-[0.8rem] leading-relaxed text-muted-foreground">
          Nothing leaves your bank without your own tap, in your own bank.
        </p>
      </PopoverContent>
    </Popover>
  );
}

/** A small padlock — gold is permitted here (chrome, not a figure). */
function LockGlyph() {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      className="text-gold"
      aria-hidden
    >
      <rect x="5" y="11" width="14" height="9" rx="1" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}
