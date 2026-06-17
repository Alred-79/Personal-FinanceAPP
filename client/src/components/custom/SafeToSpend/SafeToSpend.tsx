/**
 * <SafeToSpend/> — the glanceable hero number (v4 §5.2).
 *
 * ONE number, tabular-mono, phosphor-green (real money truth). The NUMBER is
 * identical across every mode — only the label changes (via the term catalog).
 * It also drives the browser tab title ("$412 · The Ledger"), toggleable in
 * settings.
 *
 * TFI guard (v4 §5.2): this surface deliberately shows NO category-remaining
 * bars — secondary numbers live a tap away, not here.
 */
import { useEffect } from "react";
import { useStore } from "@/store/store";
import { useTerm } from "@/store/gameMode";

const APP_NAME = "The Ledger";

/** Whole dollars, no cents under $1,000; sign-aware. Negative keeps the sign. */
export function formatSafeToSpend(amount: number): string {
  const neg = amount < 0;
  const abs = Math.abs(amount);
  const body =
    abs >= 1000
      ? abs.toLocaleString("en-US", { maximumFractionDigits: 0 })
      : abs.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return `${neg ? "-" : ""}$${body}`;
}

interface SafeToSpendProps {
  /** When false, the component does not write the browser tab title. Default
   * true; the Settings toggle flips this. */
  updateTabTitle?: boolean;
}

/**
 * Drive the browser tab title from the safe-to-spend figure ("$612 · The
 * Ledger"). Extracted so whichever component owns the Overview hero (the flat
 * SafeToSpend or the promoted SpendCard gauge) can keep the title in sync.
 * `enabled` is the Settings toggle.
 */
export function useSafeToSpendTitle(available: number | null, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    if (available === null) {
      document.title = APP_NAME;
      return;
    }
    document.title = `${formatSafeToSpend(available)} · ${APP_NAME}`;
    return () => {
      document.title = APP_NAME;
    };
  }, [available, enabled]);
}

export function SafeToSpend({ updateTabTitle = true }: SafeToSpendProps) {
  const s2s = useStore((s) => s.safeToSpend);
  const label = useTerm("money.safe_to_spend");
  const available = s2s ? s2s.available : null;

  // Drive the tab title on every data refresh.
  useSafeToSpendTitle(available, updateTabTitle);

  const isNegative = available !== null && available < 0;

  return (
    <div
      data-testid="safe-to-spend"
      className="border border-rule-strong/40 bg-card p-6 shadow-plate"
    >
      <p className="dept-label text-[10px]">{label}</p>
      <p
        className={
          // The figure guard keeps any glow/scanline off the money number; green
          // is the real-money token. Red is NEVER used here (boss-only); a
          // negative uses the standard alert style, not the boss accent.
          "ledger-figures figure mt-2 text-5xl font-semibold tabular-nums " +
          (isNegative ? "text-destructive" : "text-credit")
        }
      >
        {available === null ? "—" : formatSafeToSpend(available)}
      </p>
      {s2s ? (
        <p className="mt-2 text-xs text-muted-foreground">
          through{" "}
          {new Date(`${s2s.horizon_end}T00:00:00`).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </p>
      ) : null}
    </div>
  );
}

export default SafeToSpend;
