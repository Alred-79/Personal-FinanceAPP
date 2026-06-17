/**
 * The two-homes IA switch (v4 §10.1), with a graceful fallback.
 *
 * Full mode's home is the Expedition map; off and ambient keep Overview. But the
 * Expedition is a GAME surface — it needs `/game/expedition/` data to plot. When
 * that data isn't there (the deferred game layer / a holdout instance), full
 * mode falls back to Overview rather than landing the user on a blank map. So:
 * full + game-data → Expedition; otherwise → Overview.
 */
import { useEffect, useState } from "react";
import { useFlags } from "@/store/gameMode";
import api from "@/lib/api";
import Overview from "@/pages/Overview/Overview";
import Expedition from "@/pages/Expedition/Expedition";

export default function Home() {
  const { terminal } = useFlags(); // terminal === full mode
  const [hasExpedition, setHasExpedition] = useState(false);

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

  return terminal && hasExpedition ? <Expedition /> : <Overview />;
}
