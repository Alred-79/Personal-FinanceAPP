import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/engraving/EmptyState";
import {
  ArrowRight,
  CircleCheck,
  Sparkles,
  Flag,
  HandCoins,
  Telescope,
} from "lucide-react";
import type { NextAction, NextActionType } from "@/types";

/**
 * W8 — the "one thing today" surface. Renders EXACTLY ONE next action (or a calm
 * "you're all set"), never a wall of nudges — the neurodivergent-mode strength.
 *
 * The single action is decided SERVER-SIDE (`GET /next-action/`) by a strict
 * ranker; this component never aggregates or trims a list, it just presents the
 * one thing. When `has_action` is false it shows the calm empty state and NEVER
 * invents a task. The copy is already firewall-screened (no-shame) on the server.
 *
 * This component is mode-agnostic. Whether the home surface DEFAULTS to it is
 * gated by the `neurodivergent_mode` feature flag in the parent (Home.tsx).
 */

const ICON: Record<NextActionType, typeof ArrowRight> = {
  bridge_due: HandCoins,
  rule_proposal: HandCoins,
  challenge_ending: Flag,
  streak_recovery: Sparkles,
  auditor_finding: Telescope,
  all_set: CircleCheck,
};

const EYEBROW: Record<NextActionType, string> = {
  bridge_due: "One thing today · A move to complete",
  rule_proposal: "One thing today · A one-tap approval",
  challenge_ending: "One thing today · A challenge to finish",
  streak_recovery: "One thing today · Pick it back up",
  auditor_finding: "One thing today · Worth a look",
  all_set: "Today · All clear",
};

export function NextActionSurface() {
  const [action, setAction] = useState<NextAction | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .get("/next-action/")
      .then((r) => {
        if (!cancelled) setAction(r.data as NextAction);
      })
      .catch(() => {
        // A failed fetch should never shame or block — fall back to the calm
        // all-set state rather than an error wall.
        if (!cancelled)
          setAction({
            has_action: false,
            action_type: "all_set",
            entity_id: null,
            copy: "You're all set for today.",
            deep_link: null,
            source: null,
          });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <Card className="animate-pulse">
        <CardContent className="h-40" />
      </Card>
    );
  }

  if (!action) return null;

  // The calm empty state — a showpiece, never "nothing here", never a task.
  if (!action.has_action || action.action_type === "all_set") {
    return (
      <EmptyState
        eyebrow={EYEBROW.all_set}
        title="You're all set"
        description={action.copy}
        seed={29}
      />
    );
  }

  const Icon = ICON[action.action_type] ?? ArrowRight;

  return (
    <Card className="plate relative overflow-hidden">
      <CardContent className="flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-4">
          <div className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-gold/10 text-gold">
            <Icon className="h-5 w-5" aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="dept-label">{EYEBROW[action.action_type]}</p>
            <p className="mt-1 font-sans text-base leading-relaxed text-foreground">
              {action.copy}
            </p>
          </div>
        </div>

        {action.deep_link && (
          <Button asChild variant="default" className="shrink-0 self-start sm:self-center">
            <Link to={action.deep_link} aria-label="Open the one thing for today">
              Take a look
              <ArrowRight className="ml-1.5 h-4 w-4" aria-hidden />
            </Link>
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default NextActionSurface;
