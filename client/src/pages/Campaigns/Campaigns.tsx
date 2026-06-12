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
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Seal } from "@/components/engraving/Seal";
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

function MilestoneRow({ milestone }: { milestone: Milestone }) {
  const label = useTerm(milestone.label_term);
  return (
    <li
      className="flex items-center justify-between border-b border-border/40 py-2"
      data-testid={`milestone-${milestone.key}`}
    >
      <span className={milestone.granted ? "" : "text-muted-foreground"}>
        {label}
      </span>
      {milestone.granted ? (
        <Seal label="sealed" size={34} tone="approved" />
      ) : (
        <span className="dept-label text-[10px] text-muted-foreground">
          — open —
        </span>
      )}
    </li>
  );
}

function ChallengeLine({ challenge }: { challenge: ChallengeRow }) {
  const label = useTerm(`challenge.${challenge.key}`);
  const status = useTerm(`challenge.status.${challenge.status}`);
  return (
    <li className="flex items-center justify-between py-1.5">
      <span>
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

  return (
    <div data-testid="campaigns-page">
      <PageHeader
        title={title}
        description="The long arc. It waits for you; it never runs out."
      />

      {campaign ? (
        <>
          <Card className="mb-6">
            <CardContent className="flex items-center justify-between pt-6">
              <div>
                <span className="dept-label text-[11px]">{rankLabel}</span>
                <div
                  className="ledger-figures figure text-4xl font-semibold"
                  data-testid="campaign-rank"
                >
                  {campaign.rank}
                </div>
              </div>
              <div className="text-right">
                <span className="dept-label text-[11px]">{campaign.quarter}</span>
                {campaign.status === "paused" ? (
                  <p className="mt-1 max-w-[220px] text-sm text-muted-foreground">
                    {pausedCopy}
                  </p>
                ) : null}
              </div>
            </CardContent>
          </Card>

          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="text-base">{arcLabel}</CardTitle>
            </CardHeader>
            <CardContent>
              <ul data-testid="milestone-track">
                {campaign.milestones.map((m) => (
                  <MilestoneRow key={m.key} milestone={m} />
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      ) : (
        <Card className="mb-6">
          <CardContent className="pt-6 text-sm text-muted-foreground">
            Nothing here right now.
          </CardContent>
        </Card>
      )}

      {challenges.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{challengeTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul data-testid="challenge-list">
              {challenges.map((c) => (
                <ChallengeLine key={c.id} challenge={c} />
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
