import { useState } from "react";
import { useStore } from "@/store/store";
import { Button } from "@/components/ui/button";
import ConfirmCard from "@/components/custom/ConfirmCard/ConfirmCard";

/**
 * The one-tap Approve for a proposal notice (rule_proposal / rule_suggest).
 * Tapping mints a FRESH confirm token from the notification's stored ref (a
 * 10-minute token would be too fragile to sit in a feed), then drops in the
 * shared ConfirmCard. Shared by the bell and the Auditor's Report so the flow
 * is identical in both.
 */
export default function ProposalApprove({
  notificationId,
  label = "Approve",
  onDone,
}: {
  notificationId: number;
  label?: string;
  onDone?: () => void;
}) {
  const mintProposalToken = useStore((s) => s.mintProposalToken);
  const markNotificationRead = useStore((s) => s.markNotificationRead);
  const fetchNotifications = useStore((s) => s.fetchNotifications);
  const fetchGoals = useStore((s) => s.fetchGoals);
  const [proposal, setProposal] = useState<{
    token: string;
    summary: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const start = async () => {
    setLoading(true);
    const p = await mintProposalToken(notificationId);
    setLoading(false);
    if (p) setProposal(p);
  };

  if (proposal) {
    return (
      <div className="mt-2">
        <ConfirmCard
          summary={proposal.summary}
          token={proposal.token}
          approveLabel={label}
          onConfirmed={() => {
            markNotificationRead(notificationId);
            // The allocation touched a goal earmark — force goals to refresh.
            useStore.setState({ goalsLoaded: false });
            fetchGoals();
            fetchNotifications();
            onDone?.();
          }}
          onDecline={() => setProposal(null)}
        />
      </div>
    );
  }

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={start}
      disabled={loading}
      className="mt-2"
    >
      {loading ? "Preparing…" : label}
    </Button>
  );
}
