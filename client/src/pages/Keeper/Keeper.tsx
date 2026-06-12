/**
 * The Keeper sheet (v4 §6.1) — an OUTPUT surface, no character creation (R3).
 *
 * Visible in nav only for ambient + full; in OFF the *route* still renders but
 * redirects to Settings (the page exists in every mode — its presence in nav is
 * the flag, so the no-mode-only-pages rule holds).
 *
 * Stats are buckets/ratios, never raw dollars on the card; the tap-reveal
 * (`<Term/>`) exposes the plain label. Stats never use red (boss-only) and never
 * shame phrasing — low stats read "rebuilding"/"calibrating".
 */
import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { IntensitySelector } from "@/components/custom/IntensitySelector/IntensitySelector";
import { useFlags, useTerm } from "@/store/gameMode";
import { Term } from "@/components/custom/Term/Term";
import { StreakChip } from "@/components/custom/StreakChip/StreakChip";
import api from "@/lib/api";

interface KeeperData {
  stats: {
    vitality: { bucket: string; months: number };
    mana: number;
    armor: number;
    might: number;
    low_confidence: boolean;
  };
  level: number;
  xp: number;
  level_progress: number;
}

export default function Keeper() {
  const { gameLayer } = useFlags();
  const [data, setData] = useState<KeeperData | null>(null);
  const title = useTerm("keeper.title");
  const calibrating = useTerm("keeper.calibrating");
  const levelLabel = useTerm("keeper.level");

  useEffect(() => {
    if (!gameLayer) return; // off mode redirects; don't fetch
    api
      .get("/game/keeper/")
      .then((res) => setData(res.data))
      .catch(() => setData(null));
  }, [gameLayer]);

  // Off mode: the page exists but routes the user to Settings (no game surface).
  if (!gameLayer) {
    return <Navigate to="/settings" replace />;
  }

  return (
    <div data-testid="keeper-sheet">
      <PageHeader title={title} description="Your standing, at a glance." />

      {/* Level / XP bar */}
      <Card className="mb-6">
        <CardContent className="pt-6">
          <div className="flex items-baseline justify-between">
            <span className="dept-label text-[11px]">{levelLabel}</span>
            <span className="ledger-figures figure text-2xl font-semibold tabular-nums">
              {data ? data.level : "—"}
            </span>
          </div>
          <div className="mt-3 h-2 w-full bg-muted">
            <div
              className="h-2 bg-credit"
              style={{ width: `${(data?.level_progress ?? 0) * 100}%` }}
              data-testid="xp-bar"
            />
          </div>
        </CardContent>
      </Card>

      {data?.stats.low_confidence ? (
        <p
          data-testid="calibrating"
          className="mb-6 border border-rule-strong/40 bg-card p-3 text-sm text-muted-foreground"
        >
          {calibrating}
        </p>
      ) : null}

      {/* The four stats — bucket/ratio displays with plain-term reveals. */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard k="keeper.stat.vitality" value={data?.stats.vitality.bucket ?? "—"} />
        <StatCard k="keeper.stat.mana" value={data ? ratioLabel(data.stats.mana) : "—"} />
        <StatCard k="keeper.stat.armor" value={data ? ratioLabel(data.stats.armor) : "—"} />
        <StatCard k="keeper.stat.might" value={data ? ratioLabel(data.stats.might) : "—"} />
      </div>

      {/* Reused intensity dial. */}
      <Card className="mt-6">
        <CardContent className="pt-6">
          <IntensitySelector />
        </CardContent>
      </Card>

      {/* The streak + ward slots (package 05 fills this slot). */}
      <Card className="mt-6">
        <CardContent className="pt-6">
          <StreakChip />
        </CardContent>
      </Card>

      {/* Placeholder slots for later packages — render "coming", don't build. */}
      <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {["boss", "bestiary", "campaign"].map((slot) => (
          <ComingCard key={slot} slot={slot} />
        ))}
      </div>
    </div>
  );
}

/** A neutral ratio label — never shame phrasing, never red. */
function ratioLabel(r: number): string {
  if (r >= 1.0) return "Strong";
  if (r >= 0.6) return "Steady";
  return "Rebuilding"; // neutral, never "failed"/"behind"/"worse"/"only"
}

function StatCard({ k, value }: { k: string; value: string }) {
  return (
    <Card data-testid={`stat-${k}`}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">
          <Term k={k} />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="font-display text-xl font-semibold">{value}</p>
      </CardContent>
    </Card>
  );
}

function ComingCard({ slot }: { slot: string }) {
  const coming = useTerm("keeper.coming");
  return (
    <Card className="opacity-60" data-testid={`coming-${slot}`}>
      <CardContent className="pt-6">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {slot}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{coming}</p>
      </CardContent>
    </Card>
  );
}
