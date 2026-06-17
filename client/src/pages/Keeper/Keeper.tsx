/**
 * The Keeper sheet (v4 §6.1) — an OUTPUT surface, no character creation (R3).
 *
 * Visible in nav only for ambient + full; in OFF the *route* still renders but
 * redirects to Settings (the page exists in every mode — its presence in nav is
 * the flag, so the no-mode-only-pages rule holds).
 *
 * Stats are buckets/ratios, never raw dollars on the card; the tap-reveal
 * (`<Term/>`) exposes the plain label. Stats never use red (boss-only) and never
 * shame phrasing — low stats read "rebuilding"/"calibrating". Reading the sheet
 * writes nothing (engagement-XP hygiene) — only GETs on mount.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Link } from "react-router-dom";
import { motion } from "motion/react";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Certificate } from "@/components/engraving/Certificate";
import { SectionRule } from "@/components/engraving/SectionRule";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { IntensitySelector } from "@/components/custom/IntensitySelector/IntensitySelector";
import { useFlags, useTerm } from "@/store/gameMode";
import { Term } from "@/components/custom/Term/Term";
import { StreakChip } from "@/components/custom/StreakChip/StreakChip";
import { Homestead } from "@/components/custom/Homestead/Homestead";
import { useReducedMotion } from "@/hooks/useEnvironment";
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
  const reduce = useReducedMotion();
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

  const progress = data?.level_progress ?? 0;

  return (
    <div data-testid="keeper-sheet">
      <PageHeader title={title} description="Your standing, at a glance." reference="Folio IX · Character Sheet" />

      <Reveal className="space-y-8">
        {/* Level crest — a struck medallion + the XP rule. */}
        <RevealItem>
          <Certificate seed={9} alive className="overflow-hidden">
            <div className="flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-center">
              <LevelCrest level={data?.level ?? null} />
              <div className="flex-1 self-stretch">
                <div className="flex items-baseline justify-between">
                  <span className="dept-label text-[11px]">{levelLabel}</span>
                  <span className="font-sans text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                    {Math.round(progress * 100)}% to next
                  </span>
                </div>
                {/* XP rule — fills on mount (never whileInView; below-fold safe). */}
                <div className="mt-3 h-2.5 w-full overflow-hidden bg-muted">
                  <motion.div
                    data-testid="xp-bar"
                    className="h-full origin-left bg-credit"
                    style={{ width: `${progress * 100}%` }}
                    initial={reduce ? false : { scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
                <p className="mt-2 font-mono text-[11px] text-muted-foreground">
                  {data ? `${data.xp.toLocaleString()} XP banked` : "—"}
                </p>
              </div>
            </div>
          </Certificate>
        </RevealItem>

        {data?.stats.low_confidence ? (
          <p
            data-testid="calibrating"
            className="border border-rule-strong/40 bg-card p-3 text-sm text-muted-foreground"
          >
            {calibrating}
          </p>
        ) : null}

        {/* The four stats — bucket/ratio plates with plain-term reveals. */}
        <RevealItem>
          <SectionRule className="mb-4">Standing</SectionRule>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatPlate k="keeper.stat.vitality" seed={21} value={data?.stats.vitality.bucket ?? "—"} />
            <StatPlate k="keeper.stat.mana" seed={34} value={data ? ratioLabel(data.stats.mana) : "—"} ratio={data?.stats.mana} />
            <StatPlate k="keeper.stat.armor" seed={47} value={data ? ratioLabel(data.stats.armor) : "—"} ratio={data?.stats.armor} />
            <StatPlate k="keeper.stat.might" seed={58} value={data ? ratioLabel(data.stats.might) : "—"} ratio={data?.stats.might} />
          </div>
        </RevealItem>

        {/* Streak + the weekly Homestead reveal. */}
        <RevealItem>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card raking>
              <CardContent className="pt-6">
                <StreakChip />
              </CardContent>
            </Card>
            <Homestead />
          </div>
        </RevealItem>

        {/* The fronts — link-throughs to the other game surfaces (replaces the
            old dead "coming soon" slots; these are now real, built pages). */}
        <RevealItem>
          <SectionRule className="mb-4">Your fronts</SectionRule>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <FrontCard to="/debts" termKey="boss.label" seed={61} blurb="Debts as bosses — chip the active one down.">
              <path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z" />
            </FrontCard>
            <FrontCard to="/campaigns" termKey="campaign.title" seed={72} blurb="This quarter's arc and its milestones.">
              <path d="M5 4h11l-2 3 2 3H5zM5 4v16" />
            </FrontCard>
            <FrontCard to="/expedition" termKey="expedition.title" seed={83} blurb="The month, charted act by act.">
              <circle cx="12" cy="12" r="8" />
              <path d="M12 8l2.5 5.5L9.5 14z" />
            </FrontCard>
          </div>
        </RevealItem>

        {/* Reused intensity dial. */}
        <RevealItem>
          <Card raking>
            <CardContent className="pt-6">
              <IntensitySelector />
            </CardContent>
          </Card>
        </RevealItem>
      </Reveal>
    </div>
  );
}

/** A neutral ratio label — never shame phrasing, never red. */
function ratioLabel(r: number): string {
  if (r >= 1.0) return "Strong";
  if (r >= 0.6) return "Steady";
  return "Rebuilding"; // neutral, never "failed"/"behind"/"worse"/"only"
}

/** The struck level medallion — a gold-ringed coin with the level numeral. */
function LevelCrest({ level }: { level: number | null }) {
  return (
    <div className="relative grid h-24 w-24 shrink-0 place-items-center">
      <div
        aria-hidden
        className="absolute inset-0 rounded-full"
        style={{
          background: "radial-gradient(circle at 38% 32%, hsl(var(--gold)), hsl(var(--gold) / 0.55))",
          boxShadow: "inset 0 0 0 3px hsl(var(--paper-high) / 0.35), 0 6px 18px hsl(222 40% 4% / 0.28)",
        }}
      />
      {/* milled inner ring */}
      <div aria-hidden className="absolute inset-[7px] rounded-full border border-[hsl(46_52%_96%/0.4)]" />
      <span className="relative font-display text-3xl font-semibold leading-none text-[hsl(222_45%_11%)]">
        {level != null ? <AnimatedNumber value={level} format={(n) => String(Math.round(n))} duration={700} /> : "—"}
      </span>
    </div>
  );
}

/**
 * A stat plate: the plain-term label (tap-reveal), the bucket/ratio value, and
 * — for the ratio stats — a slim gauge. Never red, never shame copy.
 */
function StatPlate({ k, value, ratio, seed }: { k: string; value: string; ratio?: number; seed: number }) {
  const pct = ratio != null ? Math.max(0.04, Math.min(1, ratio)) : null;
  return (
    <Certificate seed={seed} className="p-5" data-testid={`stat-${k}`}>
      <p className="dept-label text-[10px]">
        <Term k={k} />
      </p>
      <p className="mt-2 font-display text-xl font-semibold">{value}</p>
      {pct != null ? (
        <div className="mt-3 h-1.5 w-full bg-muted">
          <div className="h-full bg-gold/80" style={{ width: `${pct * 100}%` }} />
        </div>
      ) : null}
    </Certificate>
  );
}

/** A link-through to another game surface — engraved facet, manicule on hover. */
function FrontCard({
  to,
  termKey,
  blurb,
  seed,
  children,
}: {
  to: string;
  termKey: string;
  blurb: string;
  seed: number;
  children: ReactNode;
}) {
  const label = useTerm(termKey);
  return (
    <Link to={to} className="group block focus-visible:outline-none">
      <Certificate seed={seed} alive className="h-full p-5">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center border border-rule-strong/40 bg-card text-gold">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              {children}
            </svg>
          </span>
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 font-display text-base font-semibold leading-tight">
              {label}
              <span className="manicule text-gold opacity-0 transition group-hover:opacity-100">☞</span>
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{blurb}</p>
          </div>
        </div>
      </Certificate>
    </Link>
  );
}
