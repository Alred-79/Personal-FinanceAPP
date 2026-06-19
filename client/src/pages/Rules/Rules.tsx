/**
 * The Rule Book (W9) — the one standing-rules management surface.
 *
 * Earlier work (W4 reflection offers, W5 Tax-Reserve funding, W7 Save-More
 * escalation) all CREATE rules on the user's behalf. Until now the only rule
 * surface was the goal-scoped `RuleEditor` embedded in the Goal dialog, so those
 * auto-created rules were invisible and unmanageable. This page lists EVERY rule
 * the user owns — whoever made it — and lets them read, pause/resume, or delete
 * each one. Pausing takes effect on the next transaction (the engine reads
 * `enabled` live; there is no rule-firing cache to go stale).
 *
 * No money ever moves here: a rule earmarks `Goal.progress` or writes a
 * notification — it never makes a real transfer. The copy says so.
 */
import { useCallback, useEffect, useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/engraving/EmptyState";
import { useToast } from "@/hooks/useToast";
import { Trash2, ScrollText } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import type { Rule } from "@/components/custom/RuleEditor/RuleEditor";

interface Goal {
  id: number;
  name: string;
}

/** A short, human description of what a rule does — engine-faithful. */
function describeRule(rule: Rule, goalName?: string): string {
  const toGoal = goalName ? ` into “${goalName}”` : "";
  const p = rule.action_params;
  switch (rule.action_type) {
    case "roundup":
      return `Rounds each purchase up to the nearest $${p.nearest ?? 1} and earmarks the change${toGoal}.`;
    case "allocate":
      if (p.amount != null)
        return `Sets aside ${formatCurrency(Number(p.amount))} per matching transaction${toGoal}.`;
      if (p.pct != null)
        return `Sets aside ${p.pct}% of each matching transaction${toGoal}.`;
      return `Sets money aside${toGoal}.`;
    case "categorize":
      return `Recategorizes matching transactions as “${String(p.category ?? "")}”.`;
    case "notify":
      return `Sends a notification when a transaction matches.`;
    default:
      return rule.name;
  }
}

/** A readable summary of the trigger conditions. */
function describeConditions(rule: Rule): string {
  if (!rule.conditions.length) return "Any transaction";
  return rule.conditions
    .map((c) => {
      const v = Array.isArray(c.value) ? c.value.join(", ") : String(c.value);
      const op =
        c.op === "eq" ? "is" : c.op === "in" ? "in" : c.op === "gt" ? ">" : c.op === "lt" ? "<" : c.op;
      return `${c.field} ${op} ${v}`;
    })
    .join(" · ");
}

export default function Rules() {
  const { toast } = useToast();
  const [rules, setRules] = useState<Rule[]>([]);
  const [goals, setGoals] = useState<Record<number, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      // No target filter → ALL rules, including the auto-created W4/W5/W7 ones.
      const [rulesRes, goalsRes] = await Promise.all([
        api.get<Rule[]>("/rules/"),
        api.get<Goal[]>("/goals/").catch(() => ({ data: [] as Goal[] })),
      ]);
      setRules(rulesRes.data);
      const byId: Record<number, string> = {};
      for (const g of goalsRes.data) byId[g.id] = g.name;
      setGoals(byId);
    } catch (error) {
      console.error("Error fetching rules:", error);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const togglePause = async (rule: Rule, enabled: boolean) => {
    setBusy(rule.id);
    // Optimistic flip so the switch feels instant; revert on failure.
    setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, enabled } : r)));
    try {
      await api.patch(`/rules/${rule.id}/`, { enabled });
      toast({ title: enabled ? "Rule resumed" : "Rule paused" });
    } catch {
      setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, enabled: !enabled } : r)));
      toast({ title: "Could not update the rule", variant: "destructive" });
    } finally {
      setBusy(null);
    }
  };

  const remove = async (rule: Rule) => {
    setBusy(rule.id);
    try {
      await api.delete(`/rules/${rule.id}/`);
      setRules((prev) => prev.filter((r) => r.id !== rule.id));
      toast({ title: "Rule deleted" });
    } catch {
      toast({ title: "Could not delete the rule", variant: "destructive" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div data-testid="rules-page">
      <PageHeader
        title="The Rule Book"
        description="Every standing rule — round-ups, auto-funding, tax reserves — in one place. Pause or remove any of them. No rule moves real money; each only earmarks toward a goal or posts a note."
      />

      {loaded && rules.length === 0 ? (
        <EmptyState
          eyebrow="Standing Rules · None yet"
          title="No rules on the books"
          description="When you set up a round-up, an auto-fund, or a tax reserve, it will appear here for you to manage."
        />
      ) : (
        <ul className="grid gap-3" data-testid="rules-list">
          {rules.map((rule) => (
            <li key={rule.id}>
              <Card data-testid={`rule-${rule.id}`} className={rule.enabled ? "" : "opacity-70"}>
                <CardContent className="flex items-start justify-between gap-4 pt-6">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <ScrollText size={14} className="shrink-0 text-gold" />
                      <span className="truncate font-display text-base font-semibold">
                        {rule.name}
                      </span>
                      <Badge variant={rule.enabled ? "default" : "outline"}>
                        {rule.enabled ? "Active" : "Paused"}
                      </Badge>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {describeRule(
                        rule,
                        rule.target_id != null ? goals[rule.target_id] : undefined
                      )}
                    </p>
                    <p className="mt-1 font-mono text-[11px] text-muted-foreground/70">
                      When: {describeConditions(rule)}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <Switch
                      data-testid={`rule-toggle-${rule.id}`}
                      aria-label={rule.enabled ? "Pause rule" : "Resume rule"}
                      checked={rule.enabled}
                      disabled={busy === rule.id}
                      onCheckedChange={(v) => togglePause(rule, v)}
                    />
                    <button
                      type="button"
                      data-testid={`rule-delete-${rule.id}`}
                      aria-label="Delete rule"
                      disabled={busy === rule.id}
                      className="text-muted-foreground transition-colors hover:text-debit disabled:opacity-50"
                      onClick={() => remove(rule)}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
