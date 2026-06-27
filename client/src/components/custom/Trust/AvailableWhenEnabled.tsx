import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * An honest "this isn't on for everyone yet" tag (docs/FRONTEND-REPOSITIONING re-eval).
 * Several capabilities — the freelancer tax desk, the nightly auditor, the game layer —
 * ship OFF by default behind an instance flag or a per-user opt-in. Advertising them as
 * if every fresh user has them is the exact overclaim we're correcting. This quiet tag
 * states the truth where such a feature is shown, with a one-tap explainer.
 *
 * Sibling of ReadOnlyBadge — same idiom (rounded-none, mono smallcaps, gold on chrome).
 */
export function AvailableWhenEnabled({
  className,
  label = "Available when enabled",
  detail,
}: {
  className?: string;
  /** Short chip copy. */
  label?: string;
  /** Plain-language explainer for the popover (what's needed to turn it on). */
  detail?: string;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-none border border-rule-strong/40 bg-transparent px-2 py-0.5",
            "font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground",
            "transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
          aria-label={`${label} — how to turn it on`}
        >
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-gold/70" />
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[17rem] rounded-none border-rule-strong/50 p-4" align="start">
        <p className="dept-label mb-1.5">Not on by default</p>
        <p className="text-[0.8rem] leading-relaxed text-foreground">
          {detail ??
            "This is switched off until your workspace turns it on (or you opt in from Settings). We'd rather say so than imply you already have it."}
        </p>
      </PopoverContent>
    </Popover>
  );
}
