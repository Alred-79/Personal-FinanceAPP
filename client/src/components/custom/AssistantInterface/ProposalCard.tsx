import { AssistantProposal } from "@/types";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Sparkline } from "@/components/engraving/Sparkline";
import { formatCurrency } from "@/lib/format";
import ConfirmCard from "@/components/custom/ConfirmCard/ConfirmCard";

/**
 * Inline what-if proposal (v6 doc 08): a compact diff (AnimatedNumber +
 * Sparkline) over the shared ConfirmCard, with a "View on Forecast" deep link.
 * Shared by the Clerk Sheet and the Command Deck so both render an identical
 * propose→confirm plate (and both carry the `assistant-proposal` testid).
 */
export function ProposalCard({
  proposal,
  onDismiss,
  onView,
}: {
  proposal: AssistantProposal;
  onDismiss: () => void;
  onView: (scenarioId: number) => void;
}) {
  const diff = proposal.diff;
  const spark = (diff?.timeline ?? []).map((p) => p.balance);
  const endingDelta = diff?.ending_balance ?? 0;

  // The approve label fits the action: a what-if commits a plan, a rule is
  // created, anything else just gets a neutral "Approve". The shared ConfirmCard
  // handles every write tool's proposal (Pillar 2.0).
  const approveLabel =
    proposal.action === "create_rule"
      ? "Create rule"
      : proposal.action === "scenario_commit"
        ? "Commit this plan"
        : "Approve";

  return (
    <div className="my-2" data-testid="assistant-proposal">
      <ConfirmCard
        summary={proposal.summary}
        token={proposal.confirm_token}
        approveLabel={approveLabel}
        onConfirmed={onDismiss}
        onDecline={onDismiss}
      >
        {diff && (
          <div className="space-y-2 rounded-none border border-rule/60 bg-card/60 p-3">
            <div className="flex items-center justify-between gap-4">
              <span className="font-sans text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                Projected ending Δ
              </span>
              <span
                className={`ledger-figures text-base ${
                  endingDelta < 0 ? "ink-debit" : "ink-credit"
                }`}
              >
                <AnimatedNumber value={endingDelta} format={(n) => formatCurrency(n)} />
              </span>
            </div>
            {spark.length > 1 && <Sparkline data={spark} width={220} height={32} />}
            {proposal.scenario_id != null && (
              <button
                type="button"
                className="font-sans text-xs text-gold underline-offset-2 hover:underline"
                onClick={() => onView(proposal.scenario_id as number)}
              >
                View on Forecast →
              </button>
            )}
          </div>
        )}
      </ConfirmCard>
    </div>
  );
}
