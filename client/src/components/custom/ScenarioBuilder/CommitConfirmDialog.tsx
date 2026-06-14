import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useStore } from "@/store/store";
import ConfirmCard from "@/components/custom/ConfirmCard/ConfirmCard";

/**
 * Commit affordance for a saved scenario (v6 doc 07/08). Proposes the
 * ``scenario_commit`` action to mint a signed summary+token, then wraps the
 * shared {@link ConfirmCard} for the confirm step. On success it refetches the
 * forecast + goals so the new standing plan is reflected.
 */
export default function CommitConfirmDialog({
  scenarioId,
  name,
  onCommitted,
}: {
  scenarioId: number;
  name: string;
  onCommitted?: () => void;
}) {
  const fetchForecast = useStore((s) => s.fetchForecast);
  const fetchGoals = useStore((s) => s.fetchGoals);
  const forecastHorizon = useStore((s) => s.forecastHorizon);

  const [proposal, setProposal] = useState<{ summary: string; token: string } | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const propose = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.post("/assistant/actions/propose/", {
        action: "scenario_commit",
        params: { scenario_id: scenarioId, name },
      });
      setProposal({ summary: resp.data.summary, token: resp.data.token });
    } catch {
      setError("Could not prepare the commit. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // Clear any stale proposal if the target scenario changes.
  useEffect(() => setProposal(null), [scenarioId]);

  if (proposal) {
    return (
      <ConfirmCard
        summary={proposal.summary}
        token={proposal.token}
        approveLabel="Commit this plan"
        onConfirmed={async () => {
          await Promise.all([
            fetchForecast(forecastHorizon || 30),
            fetchGoals(),
          ]);
          onCommitted?.();
        }}
        onDecline={() => setProposal(null)}
      />
    );
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={propose}
        disabled={loading}
        aria-label="Commit this plan"
        className="press inline-flex items-center rounded-none border border-gold/50 bg-gold/10 px-4 py-2 font-sans text-sm text-gold disabled:opacity-50"
      >
        {loading ? "Preparing…" : "Commit this plan"}
      </button>
      {error && <p className="font-sans text-xs text-debit">{error}</p>}
    </div>
  );
}
