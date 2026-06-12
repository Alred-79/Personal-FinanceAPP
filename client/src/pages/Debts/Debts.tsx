/**
 * The Debts page (v4 §7.1) — the boss-battle surface.
 *
 * A finance feature (debt tracking) wearing the boss skin in ambient/full. The
 * route exists in every mode; in off it redirects to Settings (its presence in
 * nav is the gameOnly flag). The active boss shows its HP bar + seeded creature;
 * other debts render as dormant silhouettes (name + glyph, no HP bar). Habit-
 * monsters render below, capped at two.
 *
 * All copy routes through the term catalog; agency language is forbidden (the
 * boss "holds ground"/"retreats" — the user never takes narrated damage).
 */
import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useFlags, useTerm } from "@/store/gameMode";
import { asciiCreatureText, type CreatureKind } from "@/lib/asciiCreature";
import api from "@/lib/api";

interface BossLiability {
  id: number;
  name: string;
  kind: CreatureKind;
  principal_cents: number;
  status: string;
  is_active_boss: boolean;
  boss: { hp: number | null; starting_hp: number | null; defeated: boolean; phases_broken: number[] };
}

interface Monster {
  kind: "minor" | "creeper";
  key: string;
  reason: string;
}

export default function Debts() {
  const { gameLayer } = useFlags();
  const title = useTerm("boss.label");
  const hpLabel = useTerm("boss.hp");
  const lurkersLabel = useTerm("monster.label");
  const [bosses, setBosses] = useState<BossLiability[]>([]);
  const [monsters, setMonsters] = useState<Monster[]>([]);

  useEffect(() => {
    if (!gameLayer) return;
    api.get("/game/bosses/").then((r) => setBosses(r.data.bosses)).catch(() => {});
    api.get("/game/monsters/").then((r) => setMonsters(r.data.monsters)).catch(() => {});
  }, [gameLayer]);

  if (!gameLayer) return <Navigate to="/settings" replace />;

  const active = bosses.find((b) => b.is_active_boss && b.status === "active");
  const dormant = bosses.filter((b) => b !== active && !b.status.startsWith("defeated"));

  return (
    <div data-testid="debts-page">
      <PageHeader title={title} description="Your debts, and how they fall." />

      {active ? <ActiveBoss boss={active} hpLabel={hpLabel} /> : null}

      {dormant.length > 0 ? (
        <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {dormant.map((b) => (
            <DormantSilhouette key={b.id} boss={b} />
          ))}
        </div>
      ) : null}

      {monsters.length > 0 ? (
        <Card className="mt-6" data-testid="monsters">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">{lurkersLabel}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {monsters.map((m) => (
              <MonsterRow key={`${m.kind}:${m.key}`} monster={m} />
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function ActiveBoss({ boss, hpLabel }: { boss: BossLiability; hpLabel: string }) {
  const hp = boss.boss.hp ?? boss.principal_cents;
  const start = boss.boss.starting_hp ?? boss.principal_cents;
  const pct = start > 0 ? Math.max(0, Math.min(1, hp / start)) : 0;
  return (
    <Card data-testid="active-boss">
      <CardContent className="pt-6">
        <div className="flex items-start gap-6">
          <pre
            data-testid="boss-art"
            className="font-mono text-[11px] leading-[1.1] text-gold"
            aria-hidden="true"
          >
            {asciiCreatureText({ kind: boss.kind, name: boss.name, balanceCents: start })}
          </pre>
          <div className="flex-1">
            <p className="font-display text-lg font-semibold">{boss.name}</p>
            <div className="mt-2 flex items-baseline justify-between">
              <span className="dept-label text-[10px]">{hpLabel}</span>
            </div>
            {/* HP bar — boss art is red-accented; user numbers are never red. */}
            <div className="mt-1 h-3 w-full bg-muted">
              <div
                data-testid="hp-bar"
                className="h-3 bg-debit"
                style={{ width: `${pct * 100}%` }}
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function DormantSilhouette({ boss }: { boss: BossLiability }) {
  return (
    <Card className="opacity-60" data-testid="dormant-silhouette">
      <CardContent className="pt-6">
        <p className="text-sm font-medium">{boss.name}</p>
        {/* No HP bar for dormant debts — silhouette only. */}
        <p className="text-xs uppercase tracking-wide text-muted-foreground">dormant</p>
      </CardContent>
    </Card>
  );
}

function MonsterRow({ monster }: { monster: Monster }) {
  const key = monster.kind === "creeper" ? "monster.creeper" : "monster.minor";
  const template = useTerm(key);
  const text = template
    .replace("{category}", monster.key)
    .replace("{merchant}", monster.key);
  return (
    <p data-testid={`monster-${monster.kind}`} className="text-sm text-muted-foreground">
      {text}
    </p>
  );
}
