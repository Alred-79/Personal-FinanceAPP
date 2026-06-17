/**
 * The Campaign (v4 §7.3) — the quarterly arc over expeditions.
 *
 * Three structural laws, mirrored from the backend and test-enforced here:
 *  - NON-EXPIRY: nothing on this surface renders time pressure. There is no
 *    countdown, no "expires", no "last chance" — the payload carries no
 *    time-remaining field, and the countdown-scan test walks this file.
 *  - A paused arc reads as resting, never as lost; milestones stay claimable.
 *  - Milestones derive from real events only; this page just renders grants.
 *
 * Route exists in every mode (fork-smell law); off redirects to Settings the
 * same way Keeper/Debts do. Kill switch / holdout: the API serves null and
 * this page renders its quiet empty state.
 */
import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Certificate } from "@/components/engraving/Certificate";
import { Seal } from "@/components/engraving/Seal";
import { SectionRule } from "@/components/engraving/SectionRule";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { useFlags, useTerm } from "@/store/gameMode";
import api from "@/lib/api";

interface Milestone {
  key: string;
  label_term: string;
  granted: boolean;
}

interface CampaignData {
  quarter: string;
  arc_key: string;
  status: string; // active | paused | complete — nothing else exists
  rank: string;
  lifetime_prestige: number;
  milestones: Milestone[];
}

interface ChallengeRow {
  id: number;
  key: string;
  tier: number;
  category: string;
  status: string;
  cosmetic_credit: boolean;
}

function MilestoneRow({ milestone, last }: { milestone: Milestone; last: boolean }) {
  const label = useTerm(milestone.label_term);
  return (
    <li
      className="relative flex items-start gap-4 pl-1"
      data-testid={`milestone-${milestone.key}`}
    >
      {/* node marker on the rule: a pressed seal when granted, else a hollow
          engraved ring. The connector line is drawn by the parent track. */}
      <div className="relative z-[1] grid shrink-0 place-items-center pt-0.5">
        {milestone.granted ? (
          <Seal label="sealed" size={38} tone="approved" />
        ) : (
          <span className="grid h-[38px] w-[38px] place-items-center rounded-full border border-dashed border-gold/50 bg-background">
            <span className="h-1.5 w-1.5 rounded-full bg-gold/40" />
          </span>
        )}
      </div>
      <div className={`flex-1 ${last ? "pb-0" : "pb-7"}`}>
        <p className={`font-display text-base font-semibold leading-tight ${milestone.granted ? "" : "text-muted-foreground"}`}>
          {label}
        </p>
        <p className="dept-label mt-1 text-[10px]">
          {milestone.granted ? "— sealed —" : "— open —"}
        </p>
      </div>
    </li>
  );
}

function ChallengeLine({ challenge }: { challenge: ChallengeRow }) {
  const label = useTerm(`challenge.${challenge.key}`);
  const status = useTerm(`challenge.status.${challenge.status}`);
  return (
    <li className="ledger-row flex items-center justify-between py-2.5">
      <span className="flex items-center gap-2">
        <span className="manicule text-gold">☞</span>
        {label}
        {challenge.category ? (
          <span className="text-muted-foreground"> · {challenge.category}</span>
        ) : null}
      </span>
      <span className="dept-label text-[10px]">{status}</span>
    </li>
  );
}

export default function Campaigns() {
  const { gameLayer } = useFlags();
  const [campaign, setCampaign] = useState<CampaignData | null>(null);
  const [challenges, setChallenges] = useState<ChallengeRow[]>([]);
  const title = useTerm("campaign.title");
  const rankLabel = useTerm("campaign.rank");
  const arcLabel = useTerm("campaign.milestones");
  const pausedCopy = useTerm("campaign.paused");
  const challengeTitle = useTerm("challenge.title");

  useEffect(() => {
    if (!gameLayer) return; // off mode redirects; don't fetch
    api
      .get("/game/campaigns/")
      .then((res) => setCampaign(res.data.campaign))
      .catch(() => setCampaign(null));
    api
      .get("/game/challenges/")
      .then((res) => setChallenges(res.data.challenges ?? []))
      .catch(() => setChallenges([]));
  }, [gameLayer]);

  if (!gameLayer) {
    return <Navigate to="/settings" replace />;
  }

  const granted = campaign?.milestones.filter((m) => m.granted).length ?? 0;
  const total = campaign?.milestones.length ?? 0;

  return (
    <div data-testid="campaigns-page">
      <PageHeader
        title={title}
        description="The long arc. It waits for you; it never runs out."
        reference="Folio XI · Standing of the House"
      />

      {campaign ? (
        <Reveal className="space-y-8">
          {/* Rank crest — the standing, with the quarter's progress + prestige. */}
          <RevealItem>
            <Certificate seed={11} alive className="overflow-hidden">
              <div className="flex flex-col gap-4 p-6 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <span className="dept-label text-[11px]">{rankLabel}</span>
                  <div
                    className="ledger-figures figure mt-1 font-display text-4xl font-semibold"
                    data-testid="campaign-rank"
                  >
                    {campaign.rank}
                  </div>
                  <div className="mt-3 flex items-center gap-1.5" title="Lifetime prestige">
                    {Array.from({ length: Math.min(10, Math.max(0, campaign.lifetime_prestige)) }).map((_, i) => (
                      <span key={i} className="h-2 w-2 rounded-full bg-gold/80" />
                    ))}
                    <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                      {campaign.lifetime_prestige} prestige
                    </span>
                  </div>
                </div>
                <div className="text-left sm:text-right">
                  <span className="dept-label text-[11px]">{campaign.quarter}</span>
                  <p className="mt-1 font-mono text-sm text-muted-foreground">
                    {granted} of {total} sealed
                  </p>
                  {campaign.status === "paused" ? (
                    <p className="mt-1 max-w-[240px] text-sm text-muted-foreground">
                      {pausedCopy}
                    </p>
                  ) : null}
                </div>
              </div>
            </Certificate>
          </RevealItem>

          {/* The arc — an engraved milestone track with a ruled connector. */}
          <RevealItem>
            <SectionRule className="mb-4">{arcLabel}</SectionRule>
            <Card raking>
              <CardContent className="pt-6">
                <ol data-testid="milestone-track" className="relative ml-[18px] border-l border-rule-strong/30 pl-5">
                  {campaign.milestones.map((m, i) => (
                    <MilestoneRow
                      key={m.key}
                      milestone={m}
                      last={i === campaign.milestones.length - 1}
                    />
                  ))}
                </ol>
              </CardContent>
            </Card>
          </RevealItem>

          {challenges.length > 0 ? (
            <RevealItem>
              <SectionRule className="mb-4">{challengeTitle}</SectionRule>
              <Card raking>
                <CardContent className="pt-2">
                  <ul data-testid="challenge-list">
                    {challenges.map((c) => (
                      <ChallengeLine key={c.id} challenge={c} />
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </RevealItem>
          ) : null}
        </Reveal>
      ) : (
        <Card className="mb-6">
          <CardContent className="pt-6 text-sm text-muted-foreground">
            Nothing here right now.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
