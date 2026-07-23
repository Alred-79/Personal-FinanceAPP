import { useEffect, useState } from "react";
import axios from "axios";

import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/format";
import { useStore } from "@/store/store";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Stamp } from "@/components/engraving/Stamp";

type Draft = {
  name: string;
  method: string;
  allocation: {
    total: number;
    unallocated: number;
    buffer_floor: { current: number; delta: number; proposed: number };
    goals: Array<{
      goal_id: number;
      name: string;
      current_progress: number;
      delta: number;
      proposed_progress: number;
    }>;
  };
  evaluation: {
    scenario: {
      result: { safe_to_spend: number; ending_balance: number };
      delta: { safe_to_spend: number; ending_balance: number };
    };
  };
  assumptions: string[];
};

type Preview = {
  persistable: false;
  disclosure: string;
  requested_max: number;
  baseline_non_negative_cap: number;
  amount_modeled: number;
  drafts: Draft[];
};

export default function PlanComposerPanel() {
  const goals = useStore((state) => state.goals);
  const goalsLoaded = useStore((state) => state.goalsLoaded);
  const fetchGoals = useStore((state) => state.fetchGoals);
  const [maximum, setMaximum] = useState("250");
  const [buffer, setBuffer] = useState("100");
  const [selected, setSelected] = useState<number[]>([]);
  const [priority, setPriority] = useState("balanced");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!goalsLoaded) fetchGoals();
  }, [fetchGoals, goalsLoaded]);

  const activeGoals = goals.filter((goal) => !goal.completed && goal.id != null);
  const run = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await api.post<Preview>("/scenarios/compose-preview/", {
        max_allocation: Number(maximum),
        additional_buffer_floor: Number(buffer),
        goal_ids: selected,
        priority,
        horizon_days: 90,
      });
      setPreview(response.data);
    } catch (requestError: unknown) {
      setPreview(null);
      const detail = axios.isAxiosError<{ detail?: string }>(requestError)
        ? requestError.response?.data?.detail
        : undefined;
      setError(detail ?? "This preview could not be composed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card raking>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>Soft-allocation composer</CardTitle>
          <p className="mt-1 font-sans text-xs text-muted-foreground">
            Compare spending-floor and goal-label drafts against the same model.
          </p>
        </div>
        <Stamp still>Nothing moves</Stamp>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="border border-gold/35 bg-gold/5 p-3 font-sans text-xs text-muted-foreground">
          <strong className="text-foreground">Soft labels only—nothing moves.</strong>{" "}
          The buffer is a spending floor, not money held in a funded reserve. These
          drafts cannot be saved, committed, applied, or transferred.
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 font-sans text-xs">
            <span className="dept-label">Maximum to model</span>
            <Input
              aria-label="Maximum soft allocation"
              type="number"
              min="0"
              step="0.01"
              value={maximum}
              onChange={(event) => setMaximum(event.target.value)}
            />
          </label>
          <label className="space-y-1.5 font-sans text-xs">
            <span className="dept-label">Additional spending floor</span>
            <Input
              aria-label="Additional spending floor"
              type="number"
              min="0"
              step="0.01"
              value={buffer}
              onChange={(event) => setBuffer(event.target.value)}
            />
          </label>
        </div>

        <div className="space-y-2">
          <p className="dept-label">Existing goals to include</p>
          <div className="flex flex-wrap gap-2">
            {activeGoals.length === 0 ? (
              <p className="font-sans text-xs italic text-muted-foreground">No active goals.</p>
            ) : activeGoals.map((goal) => {
              const id = goal.id!;
              const on = selected.includes(id);
              return (
                <Button
                  key={id}
                  type="button"
                  size="sm"
                  variant={on ? "default" : "outline"}
                  aria-pressed={on}
                  onClick={() => setSelected((ids) => on ? ids.filter((x) => x !== id) : [...ids, id])}
                >
                  {goal.name}
                </Button>
              );
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-2">
            <p className="dept-label">Show first</p>
            <div className="flex gap-2">
              {(["buffer", "balanced", "deadlines"] as const).map((item) => (
                <button
                  type="button"
                  key={item}
                  aria-pressed={priority === item}
                  onClick={() => setPriority(item)}
                  className={cn(
                    "border px-3 py-1.5 font-sans text-xs capitalize",
                    priority === item ? "border-gold bg-gold/10" : "border-rule-strong/40"
                  )}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
          <Button type="button" onClick={run} disabled={loading || Number(maximum) < 0}>
            {loading ? "Modeling…" : "Preview drafts"}
          </Button>
        </div>
        {error && <p role="alert" className="font-sans text-xs text-debit">{error}</p>}

        {preview && (
          <div className="space-y-3">
            <p className="font-sans text-xs text-muted-foreground">
              Modeled {formatCurrency(preview.amount_modeled)}; the current non-negative
              Safe-to-Spend cap is {formatCurrency(preview.baseline_non_negative_cap)}.
            </p>
            <div className="grid gap-3 lg:grid-cols-3">
              {preview.drafts.map((draft) => (
                <div key={draft.name} className="border border-rule-strong/35 bg-card p-4">
                  <p className="font-display font-semibold">{draft.name}</p>
                  <p className="mt-2 font-sans text-xs text-muted-foreground">
                    Spending floor +{formatCurrency(draft.allocation.buffer_floor.delta)}
                  </p>
                  {draft.allocation.goals.map((goal) => (
                    <p key={goal.goal_id} className="mt-1 font-sans text-xs text-muted-foreground">
                      {goal.name} label +{formatCurrency(goal.delta)}
                    </p>
                  ))}
                  <div className="mt-3 border-t border-rule pt-3 font-mono text-xs">
                    Safe-to-Spend {formatCurrency(draft.evaluation.scenario.result.safe_to_spend)}
                    <span className="ml-1 text-muted-foreground">
                      ({draft.evaluation.scenario.delta.safe_to_spend >= 0 ? "+" : ""}
                      {formatCurrency(draft.evaluation.scenario.delta.safe_to_spend)})
                    </span>
                  </div>
                  {draft.allocation.unallocated > 0 && (
                    <p className="mt-2 font-sans text-[11px] text-muted-foreground">
                      {formatCurrency(draft.allocation.unallocated)} remains unallocated.
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
