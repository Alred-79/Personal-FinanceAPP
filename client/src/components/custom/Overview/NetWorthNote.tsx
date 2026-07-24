import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Guilloche, GuillocheBand } from "@/components/engraving/Guilloche";
import { Brandmark } from "@/components/layout/Brandmark";

/**
 * The hero of the Overview: net worth rendered as an actual engraved banknote.
 * Guilloché rosettes in the corners, a woven security band, microprint, a
 * serial number, and the headline figure set in intaglio. It IS the money.
 */
export default function NetWorthNote() {
  const { netWorth, user } = useStore();

  const current = netWorth.length > 0 ? netWorth[netWorth.length - 1].total : 0;

  const delta = (() => {
    if (netWorth.length < 2) return null;
    const last = netWorth[netWorth.length - 1];
    const target = new Date(last.date);
    target.setDate(target.getDate() - 30);
    let prev = netWorth[0];
    for (const snap of netWorth) {
      if (new Date(snap.date) <= target) prev = snap;
    }
    if (prev === last) return null;
    return last.total - prev.total;
  })();

  const pctDelta =
    delta !== null && current - delta !== 0
      ? (delta / Math.abs(current - delta)) * 100
      : null;

  // A stable pseudo-serial drawn from the holder's name + figure.
  const serial = `A ${String(Math.abs(Math.round(current * 7) % 9000000) + 1000000)} L`;
  const holder = (user?.full_name || user?.username || "Bearer").toUpperCase();

  return (
    <section
      className="plate relative overflow-hidden bg-card animate-ink-in"
      aria-label="Net worth certificate"
    >
      {/* Corner rosettes */}
      <div className="pointer-events-none absolute -left-10 -top-10 text-gold/25">
        <Guilloche size={180} rings={6} seed={7} />
      </div>
      <div className="pointer-events-none absolute -bottom-12 -right-12 text-gold/20">
        <Guilloche size={210} rings={7} seed={42} animate />
      </div>

      {/* Top security band */}
      <div className="relative text-gold/40">
        <GuillocheBand height={20} waves={5} seed={11} />
      </div>

      <div className="relative grid gap-6 p-7 md:grid-cols-[1.4fr_1fr] md:p-9">
        {/* Left: denomination */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="dept-label">Statement of Net Worth</p>
            <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-debit">
              № {serial}
            </p>
          </div>

          <div>
            <p className="mb-1 font-sans text-[11px] uppercase tracking-[0.3em] text-muted-foreground">
              Pay to the order of {holder}
            </p>
            <p className="intaglio text-5xl leading-none text-foreground md:text-6xl">
              <AnimatedNumber value={current} />
            </p>
          </div>

          {delta !== null && (
            <div className="flex items-center gap-3">
              <span
                className={`inline-flex items-center gap-1 font-mono text-sm ${
                  delta >= 0 ? "ink-credit" : "ink-debit"
                }`}
              >
                {delta >= 0 ? "▲" : "▼"} {formatCurrency(Math.abs(delta))}
                {pctDelta !== null && (
                  <span className="opacity-70">
                    ({pctDelta >= 0 ? "+" : ""}
                    {pctDelta.toFixed(1)}%)
                  </span>
                )}
              </span>
              <span className="font-sans text-xs italic text-muted-foreground">
                these thirty days past
              </span>
            </div>
          )}

          <p className="microprint max-w-md">
            {"NET·WORTH·NET·WORTH·NET·WORTH·NET·WORTH·NET·WORTH·NET·WORTH·NET·WORTH·NET·WORTH·".repeat(
              2
            )}
          </p>
        </div>

        {/* Right: seal + trend medallion */}
        <div className="flex flex-col items-center justify-center gap-4 border-rule-strong/30 md:border-l md:pl-8">
          <div className="relative grid place-items-center">
            <span className="absolute text-gold/30">
              <Guilloche size={130} rings={5} seed={3} animate />
            </span>
            <span className="text-gold">
              <Brandmark size={64} />
            </span>
          </div>
          <p className="text-center text-[9px] uppercase tracking-[0.28em] text-muted-foreground">
            Calculated account position
          </p>
        </div>
      </div>

      {/* Bottom security band */}
      <div className="relative rotate-180 text-gold/40">
        <GuillocheBand height={20} waves={5} seed={11} />
      </div>
    </section>
  );
}
