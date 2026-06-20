import { Earmark } from "@/types";
import { formatCurrency } from "@/lib/format";

// Engraved chart inks for the earmark bands (skip --chart-3, reserved for the
// running-balance idiom elsewhere). The remainder uses --credit.
const BAND_VARS = ["--chart-1", "--chart-2", "--chart-4", "--chart-5", "--chart-6"];

/**
 * A 2D segmented "jar" progress bar: the filled portion is partitioned into the
 * goal's named earmark bands, with the unallocated remainder in credit-green and
 * the empty remainder showing the track. The 2D echo of the 3D phial's strata.
 */
export function JarBar({
  progress,
  amount,
  earmarks = [],
  reduce = false,
}: {
  progress: number;
  amount: number;
  earmarks?: Earmark[];
  reduce?: boolean;
}) {
  const fill = amount > 0 ? Math.min(1, progress / amount) : 0;
  const segments: { w: number; color: string; name: string; amount: number }[] =
    [];

  if (progress > 0 && amount > 0) {
    let acc = 0;
    earmarks.forEach((e, i) => {
      const w = Math.max(0, Math.min(1, e.amount / amount));
      segments.push({
        w,
        color: `hsl(var(${BAND_VARS[i % BAND_VARS.length]}))`,
        name: e.name,
        amount: e.amount,
      });
      acc += w;
    });
    const remainder = Math.max(0, fill - acc);
    if (remainder > 0.001) {
      const allocated = earmarks.reduce((s, e) => s + e.amount, 0);
      segments.push({
        w: remainder,
        color: "hsl(var(--credit))",
        name: "Unallocated",
        amount: Math.max(0, progress - allocated),
      });
    }
  }

  return (
    <div className="flex h-2 w-full overflow-hidden border border-rule-strong/40 bg-secondary">
      {segments.map((s, i) => (
        <div
          key={i}
          className={
            reduce ? "" : "transition-[width] duration-700 ease-out"
          }
          style={{ width: `${s.w * 100}%`, background: s.color }}
          title={`${s.name} · ${formatCurrency(s.amount)}`}
        />
      ))}
    </div>
  );
}
