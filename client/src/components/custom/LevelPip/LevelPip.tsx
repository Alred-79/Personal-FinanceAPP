/**
 * <LevelPip /> — the tiny level indicator in the app header (v4 §6.1, task 3).
 *
 * Present only when the game layer is on (ambient + full); renders NOTHING in
 * off mode — the pip's presence is gated by the same flag the Keeper nav entry
 * uses, so off mode stays pixel-identical to the pre-game shell.
 *
 * It is a pure OUTPUT: it reads the already-derived level from the Keeper read
 * surface and never writes an event (viewing it awards no XP — the engagement-
 * XP hygiene rule). The level number routes through the term catalog via the
 * `keeper.level` key so the label follows the mode's vocabulary.
 */
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Shield } from "lucide-react";
import { useFlags, useTerm } from "@/store/gameMode";
import api from "@/lib/api";

export function LevelPip() {
  const { gameLayer } = useFlags();
  const [level, setLevel] = useState<number | null>(null);
  const levelLabel = useTerm("keeper.level");

  useEffect(() => {
    if (!gameLayer) return; // off mode: no pip, no fetch
    let cancelled = false;
    api
      .get("/game/keeper/")
      .then((res) => {
        if (!cancelled) setLevel(res.data?.level ?? null);
      })
      .catch(() => {
        /* best-effort; the pip simply stays empty if the read fails */
      });
    return () => {
      cancelled = true;
    };
  }, [gameLayer]);

  // Off mode: render nothing at all (presence is the flag).
  if (!gameLayer) return null;

  return (
    <NavLink
      to="/keeper"
      aria-label={levelLabel}
      data-testid="level-pip"
      className="press grid h-9 place-items-center gap-1 border border-rule-strong/50 bg-card px-2 text-foreground shadow-plate transition-all hover:bg-wash"
    >
      <span className="flex items-center gap-1">
        <Shield className="h-[15px] w-[15px] shrink-0 opacity-80" />
        <span className="font-mono text-[12px] font-semibold tabular-nums">
          {level ?? "—"}
        </span>
      </span>
    </NavLink>
  );
}

export default LevelPip;
