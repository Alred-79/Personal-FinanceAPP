/**
 * The Debts page (v4 §7.1) — the boss-battle surface.
 *
 * A finance feature (debt tracking) wearing the boss skin in ambient/full. The
 * route exists in every mode; in off it redirects to Settings (its presence in
 * nav is the gameOnly flag). FULL mode renders the active debt as a held
 * TERRITORY that recedes as you pay it down (+ a VANQUISHED seal when cleared);
 * AMBIENT keeps the plainer engraved boss panel (ASCII sigil + HP rule). Other
 * debts render as dormant silhouettes; habit-monsters fill a small bestiary.
 *
 * All copy routes through the term catalog; agency language is forbidden (the
 * boss "holds ground"/"retreats" — the user never takes narrated damage). Red
 * is the boss and only the boss: the territory, the HP rule, the active kicker.
 * Money figures stay sober; a debt balance may read in debit ink (money owed).
 */
import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { SectionRule } from "@/components/engraving/SectionRule";
import { Stamp } from "@/components/engraving/Stamp";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { BossTerritory } from "@/components/custom/BossTerritory/BossTerritory";
import { BestiaryCreature } from "@/components/custom/Bestiary/BestiaryCreature";
import { useFlags, useTerm } from "@/store/gameMode";
import { asciiCreatureText, hashSeed, type CreatureKind } from "@/lib/asciiCreature";
import { formatCurrency } from "@/lib/format";
import api from "@/lib/api";

interface BossLiability {
  id: number;
  name: string;
  kind: CreatureKind;
  principal_cents: number;
  minimum_payment_cents: number;
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
  const { gameLayer, terminal } = useFlags();
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
      <PageHeader title={title} description="Your debts, and how they fall." reference="Folio X · The Adversaries" />

      <Reveal className="space-y-8">
        {active ? (
          <RevealItem>
            <ActiveBoss boss={active} hpLabel={hpLabel} terminal={terminal} />
          </RevealItem>
        ) : null}

        {dormant.length > 0 ? (
          <RevealItem>
            <SectionRule className="mb-4">Dormant</SectionRule>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              {dormant.map((b) => (
                <DormantSilhouette key={b.id} boss={b} />
              ))}
            </div>
          </RevealItem>
        ) : null}

        {monsters.length > 0 ? (
          <RevealItem>
            <SectionRule className="mb-4">{lurkersLabel}</SectionRule>
            <div data-testid="monsters" className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {monsters.map((m) => (
                <BestiaryEntry key={`${m.kind}:${m.key}`} monster={m} breathe={terminal} />
              ))}
            </div>
          </RevealItem>
        ) : null}
      </Reveal>
    </div>
  );
}

function ActiveBoss({ boss, hpLabel, terminal }: { boss: BossLiability; hpLabel: string; terminal: boolean }) {
  const hp = boss.boss.hp ?? boss.principal_cents;
  const start = boss.boss.starting_hp ?? boss.principal_cents;
  const pct = start > 0 ? Math.max(0, Math.min(1, hp / start)) : 0;
  const defeated = boss.boss.defeated || pct <= 0;
  const remaining = formatCurrency((hp ?? 0) / 100);

  return (
    <Card data-testid="active-boss" className="overflow-hidden">
      <CardContent className="pt-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="dept-label text-[10px]" style={{ color: "hsl(var(--boss-accent))" }}>
              Active quarry
            </p>
            <p className="font-display text-2xl font-semibold leading-tight">{boss.name}</p>
          </div>
          <div className="text-right">
            <span className="dept-label text-[10px]">{hpLabel}</span>
            <p className="ledger-figures figure ink-debit text-2xl font-semibold">{remaining}</p>
          </div>
        </div>

        {terminal ? (
          /* FULL — the held territory recedes as the balance falls. */
          <div className="relative mt-4 h-[210px] overflow-hidden border border-rule-strong/40 bg-wash/40">
            <BossTerritory fraction={pct} seed={hashSeed(boss.name)} className="absolute inset-0" />
            {defeated ? (
              <div className="absolute inset-0 grid place-items-center">
                <Stamp variant="gold">Vanquished</Stamp>
              </div>
            ) : null}
            <div className="absolute inset-x-4 bottom-3">
              <div className="h-2 w-full bg-rule-strong/25">
                <div
                  data-testid="hp-bar"
                  className="h-2"
                  style={{ width: `${pct * 100}%`, background: "hsl(var(--boss-accent))" }}
                />
              </div>
              <div className="mt-1 flex justify-between font-mono text-[11px]">
                <span className="text-muted-foreground">{Math.round(pct * 100)}% holds ground</span>
                <span className="text-muted-foreground">forecast-driven</span>
              </div>
            </div>
          </div>
        ) : (
          /* AMBIENT — the plainer engraved panel: sigil + HP rule. */
          <div className="mt-4 flex items-start gap-6">
            <pre
              data-testid="boss-art"
              className="font-mono text-[11px] leading-[1.1] text-gold"
              aria-hidden="true"
            >
              {asciiCreatureText({ kind: boss.kind, name: boss.name, balanceCents: start })}
            </pre>
            <div className="flex-1">
              <div className="mt-1 h-3 w-full bg-muted">
                <div
                  data-testid="hp-bar"
                  className="h-3"
                  style={{ width: `${pct * 100}%`, background: "hsl(var(--boss-accent))" }}
                />
              </div>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                {Math.round(pct * 100)}% holds ground
              </p>
            </div>
          </div>
        )}

        {boss.minimum_payment_cents === 0 ? (
          <p data-testid="min-payment-hint" className="mt-3 text-xs text-muted-foreground">
            Set this debt's minimum payment to land critical hits when you pay more than the minimum.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function DormantSilhouette({ boss }: { boss: BossLiability }) {
  return (
    <Card className="opacity-70" data-testid="dormant-silhouette">
      <CardContent className="flex items-center gap-3 pt-6">
        <span className="grid h-10 w-10 shrink-0 place-items-center border border-rule-strong/40 text-rule-strong/70">
          <BestiaryCreature seed={hashSeed(boss.name)} className="h-7 w-7" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{boss.name}</p>
          <p className="dept-label text-[10px] text-muted-foreground">dormant</p>
        </div>
      </CardContent>
    </Card>
  );
}

/** One bestiary specimen — engraved creature, name, status, and the reason. */
function BestiaryEntry({ monster, breathe }: { monster: Monster; breathe: boolean }) {
  const key = monster.kind === "creeper" ? "monster.creeper" : "monster.minor";
  const template = useTerm(key);
  const text = template.replace("{category}", monster.key).replace("{merchant}", monster.key);
  const tamed = false; // an active lurker; tamed specimens would ink in gold.
  return (
    <div data-testid={`monster-${monster.kind}`} className="plate flex flex-col items-center gap-2 bg-card p-5 text-center">
      <BestiaryCreature seed={hashSeed(monster.key)} tamed={tamed} breathe={breathe} className="h-[88px] w-[132px] text-rule-strong" />
      <h4 className="font-display text-[0.95rem] font-semibold">{monster.key}</h4>
      <span className="dept-label text-[10px]">
        {monster.kind === "creeper" ? "creeping" : "stalking"}
      </span>
      <p className="text-xs leading-relaxed text-muted-foreground">{text}</p>
    </div>
  );
}
