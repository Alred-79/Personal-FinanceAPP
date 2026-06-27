import { cn } from "@/lib/utils";

/**
 * A quiet inline assurance for any surface where the assistant proposes an
 * action: nothing happens until the human taps. Pairs with the Bridge's
 * three-state chip — this is the steady-state promise, the chip is the live
 * status. Decorative-free, gold reserved for the glyph (chrome only).
 */
export function HumanInLoopBadge({
  className,
  label = "Nothing happens until you tap",
}: {
  className?: string;
  label?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground",
        className,
      )}
    >
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
        <path d="M9 11V6a2 2 0 0 1 4 0v5" />
        <path d="M13 7a2 2 0 0 1 4 0v6a6 6 0 0 1-6 6h-1.5a4 4 0 0 1-3-1.4L3 13.5a1.8 1.8 0 0 1 2.7-2.4L7 12" />
      </svg>
      {label}
    </span>
  );
}
