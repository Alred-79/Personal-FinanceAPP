/**
 * The two-homes IA switch (v4 §10.1), with a graceful fallback — plus the W8
 * neurodivergent-mode single-action surface.
 *
 * Full mode's home is the Expedition map; off and ambient keep Overview. But the
 * Expedition is a GAME surface — it needs `/game/expedition/` data to plot. When
 * that data isn't there (the deferred game layer / a holdout instance), full
 * mode falls back to Overview rather than landing the user on a blank map. So:
 * full + game-data → Expedition; otherwise → Overview.
 *
 * W8: when the instance has `neurodivergent_mode` on (read from `/settings/`
 * features), the home DEFAULTS to the calm "one thing today" surface above the
 * usual overview — exactly one next action, never a wall of nudges. The flag only
 * drives this DEFAULTING; the `/next-action/` endpoint works regardless (B4).
 */
import { useEffect, useState } from "react";
import { useFlags } from "@/store/gameMode";
import api from "@/lib/api";
import Overview from "@/pages/Overview/Overview";
import Expedition from "@/pages/Expedition/Expedition";
import { NextActionSurface } from "@/components/custom/NextAction/NextActionSurface";

export default function Home() {
  const { terminal } = useFlags(); // terminal === full mode
  const [hasExpedition, setHasExpedition] = useState(false);
  // W8: instance-level neurodivergent mode → default to the single-action surface.
  const [neurodivergent, setNeurodivergent] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get("/settings/")
      .then((r) => {
        if (!cancelled)
          setNeurodivergent(Boolean(r.data?.features?.neurodivergent_mode));
      })
      .catch(() => {
        if (!cancelled) setNeurodivergent(false); // flag off is the safe default
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!terminal) {
      setHasExpedition(false);
      return;
    }
    let cancelled = false;
    api
      .get("/game/expedition/")
      .then((r) => {
        if (!cancelled) setHasExpedition((r.data?.map?.acts?.length ?? 0) > 0);
      })
      .catch(() => {
        if (!cancelled) setHasExpedition(false);
      });
    return () => {
      cancelled = true;
    };
  }, [terminal]);

  const base = terminal && hasExpedition ? <Expedition /> : <Overview />;

  // Neurodivergent mode leads with the calm single-action surface, then the
  // usual home below it. Flag off → identical to today (just the base home).
  if (neurodivergent) {
    return (
      <>
        <div className="mb-6">
          <NextActionSurface />
        </div>
        {base}
      </>
    );
  }
  return base;
}
