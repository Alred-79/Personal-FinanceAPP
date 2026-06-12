/**
 * <StreakChip /> — the streak + ward indicator (v4 §6.2).
 *
 * The display contract is structural here: the data model has no "broken"
 * state, so a lapsed streak arrives as ``status: "rebuilding"`` and renders
 * "Rebuilding — day N (best: M)" — never "broken", "lost", or a bare "0".
 *
 * Hidden entirely in off mode (no streak chrome anywhere). Ambient renders the
 * plain copy; full uses the flavored catalog. Reading the streak writes nothing.
 */
import { useEffect, useState } from "react";
import { useFlags, useGameMode } from "@/store/gameMode";
import api from "@/lib/api";

interface StreakData {
  status: "active" | "rebuilding" | "reviving";
  current: number;
  best: number;
  wards: number;
  grace_wards: number;
  tick_collectible: number;
  reviving: boolean;
}

/** Fill a "{n}"/"{best}" template — the only formatting the chip does. */
function fill(template: string, vars: Record<string, number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
}

export function StreakChip() {
  const { gameLayer } = useFlags();
  const { term } = useGameMode();
  const [data, setData] = useState<StreakData | null>(null);

  useEffect(() => {
    if (!gameLayer) return;
    let cancelled = false;
    api
      .get("/game/streak/")
      .then((res) => !cancelled && setData(res.data))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [gameLayer]);

  if (!gameLayer || !data) return null;

  let label: string;
  if (data.status === "reviving") {
    label = fill(term("streak.reviving"), { n: data.current, best: data.best });
  } else if (data.status === "rebuilding") {
    // NEVER "broken" / "0" — the rebuilding template carries the best run.
    label = fill(term("streak.rebuilding"), { n: 1, best: data.best });
  } else {
    label = fill(term("streak.active"), { n: data.current, best: data.best });
  }

  const wardSlots = data.wards + data.grace_wards;

  return (
    <div
      data-testid="streak-chip"
      className="flex items-center gap-3 text-[12px] font-semibold uppercase tracking-[0.14em] text-muted-foreground"
    >
      <span data-testid="streak-label">{label}</span>
      <span
        data-testid="ward-slots"
        aria-label={term("ward.label")}
        className="flex items-center gap-1"
      >
        {Array.from({ length: 2 }).map((_, i) => (
          <span
            key={i}
            className={
              i < wardSlots
                ? "h-2 w-2 rounded-full bg-gold"
                : "h-2 w-2 rounded-full border border-rule-strong/50"
            }
          />
        ))}
      </span>
    </div>
  );
}

export default StreakChip;
