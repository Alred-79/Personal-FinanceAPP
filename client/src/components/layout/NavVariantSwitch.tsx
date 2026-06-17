import { cn } from "@/lib/utils";
import { NAV_VARIANTS, setNavVariant, useNavVariant } from "@/lib/navVariant";

/**
 * TEMP — segmented control to flip between the three nav treatments live so the
 * look can be chosen. Remove this (and `lib/navVariant`, the losing variants)
 * once a winner is picked.
 */
export function NavVariantSwitch() {
  const variant = useNavVariant();
  return (
    <div
      className="hidden items-center border border-rule-strong/40 bg-card shadow-plate md:flex"
      title="TEMP — choose a nav style"
    >
      {NAV_VARIANTS.map(({ key, label }) => (
        <button
          key={key}
          onClick={() => setNavVariant(key)}
          className={cn(
            "px-2 py-1.5 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors",
            variant === key
              ? "bg-gold text-background"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
