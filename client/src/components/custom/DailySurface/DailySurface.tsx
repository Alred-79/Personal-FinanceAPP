/**
 * <DailySurface /> — today's one verb + the collect affordance (v4 §6.2/§6.3).
 *
 * NEVER more than these two elements (the CHI PLAY obligation-pest finding: a
 * daily surface that grows into a checklist becomes a chore). The verb is fully
 * skippable and skipping is unremarked. Collect reveals the already-accrued tick
 * and awards nothing extra. Hidden in off mode.
 *
 * This is a card on Overview for now; the Expedition home (package 08) replaces
 * it as the daily surface.
 */
import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { useFlags, useTerm } from "@/store/gameMode";
import api from "@/lib/api";

interface StreakData {
  tick_collectible: number;
}

export function DailySurface({ verb }: { verb?: string | null }) {
  const { gameLayer } = useFlags();
  const [tick, setTick] = useState(0);
  const [collected, setCollected] = useState(false);
  const collectLabel = useTerm("tick.collect");
  const dailyTitle = useTerm("daily.title");
  // The verb prompt is term-driven; default to the worth-it tag when unset.
  const verbLabel = useTerm(`daily.verb.${verb ?? "worth_it_tag"}`);

  useEffect(() => {
    if (!gameLayer) return;
    let cancelled = false;
    api
      .get("/game/streak/")
      .then((res) => !cancelled && setTick((res.data as StreakData).tick_collectible))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [gameLayer]);

  if (!gameLayer) return null;

  async function collect() {
    try {
      await api.post("/game/tick/collect/");
      setCollected(true);
      setTick(0);
    } catch {
      /* best-effort */
    }
  }

  return (
    <Card data-testid="daily-surface">
      <CardContent className="flex items-center justify-between gap-4 pt-6">
        {/* Element 1: today's verb (a prompt; tapping it routes to the action). */}
        <span data-testid="daily-verb" className="text-sm font-medium">
          <span className="dept-label mr-2 text-[10px]">{dailyTitle}</span>
          {verbLabel}
        </span>

        {/* Element 2: the collect affordance — reveals the accrued tick (XP, no $). */}
        <button
          data-testid="tick-collect"
          onClick={collect}
          disabled={collected || tick === 0}
          className="press border border-rule-strong/50 bg-card px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground shadow-plate transition-all hover:bg-wash disabled:opacity-50"
        >
          {collectLabel}
          {tick > 0 ? ` (${tick})` : ""}
        </button>
      </CardContent>
    </Card>
  );
}

export default DailySurface;
