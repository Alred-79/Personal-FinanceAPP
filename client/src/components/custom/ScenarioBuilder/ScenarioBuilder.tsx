import { useEffect, useMemo, useState } from "react";
import { useStore } from "@/store/store";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Stamp } from "@/components/engraving/Stamp";
import { GuillocheBand } from "@/components/engraving/Guilloche";
import { blankMutation, toOverlayPayload } from "@/lib/scenario";
import type { ScenarioMutation, ScenarioMutationKind } from "@/types";

const KIND_LABELS: Partial<Record<ScenarioMutationKind, string>> = {
  income: "Recurring income",
  expense: "Recurring expense",
  oneoff: "One-time flow",
  goal: "Goal change",
  balance: "Starting balance",
};

const RECURRENCES = ["daily", "weekly", "bi-weekly", "monthly", "quarterly", "annually"];
const DEFAULT_START = new Date().toISOString().slice(0, 10);
const DEFAULT_END = new Date(Date.now() + 90 * 86_400_000).toISOString().slice(0, 10);
const NOOP = () => {};

export default function ScenarioBuilder({
  initialMutations,
  initialName,
  scenarioId,
  horizonDays = 90,
  horizonStart = DEFAULT_START,
  horizonEnd = DEFAULT_END,
  onSaved,
}: {
  initialMutations?: ScenarioMutation[];
  initialName?: string;
  scenarioId?: number;
  horizonDays?: number;
  horizonStart?: string;
  horizonEnd?: string;
  onSaved?: (id: number) => void;
}) {
  const goals = useStore((s) => s.goals);
  const runScenario = useStore((s) => s.runScenario);
  const clearResult = useStore((s) => s.clearActiveScenarioResult) ?? NOOP;
  const createScenario = useStore((s) => s.createScenario);
  const updateScenario = useStore((s) => s.updateScenario);
  const [name, setName] = useState(initialName ?? "");
  const [mutations, setMutations] = useState<ScenarioMutation[]>(initialMutations ?? []);
  const [saving, setSaving] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluatedSignature, setEvaluatedSignature] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (initialMutations) setMutations(initialMutations);
    if (initialName !== undefined) setName(initialName);
  }, [initialMutations, initialName]);

  const overlay = useMemo(() => toOverlayPayload(mutations), [mutations]);
  const signature = useMemo(
    () => JSON.stringify({ horizonDays, overlay }),
    [horizonDays, overlay]
  );
  const errors = useMemo(() => validateMutations(mutations), [mutations]);
  const hasBalanceOverride = mutations.some((mutation) => mutation.kind === "balance");
  const valid = mutations.length > 0 && errors.size === 0;
  const stale = evaluatedSignature !== signature;

  const markChanged = (next: ScenarioMutation[]) => {
    setMutations(next);
    setMessage(evaluatedSignature ? "Assumptions changed. Evaluate again before saving." : null);
    clearResult();
  };

  useEffect(() => {
    if (evaluatedSignature && evaluatedSignature !== signature) {
      setMessage("Horizon changed. Evaluate again before saving.");
      clearResult();
    }
  }, [signature, evaluatedSignature, clearResult]);

  const addRow = (kind: ScenarioMutationKind, flowKind?: "income" | "expense") => {
    const row = blankMutation(kind);
    if (row.kind === "oneoff") {
      row.flowKind = flowKind ?? "expense";
      row.date = horizonStart;
      row.title = flowKind === "income" ? "One-time income" : "Purchase";
    }
    markChanged([...mutations, row]);
  };
  const patchRow = (id: string, patch: Partial<ScenarioMutation>) =>
    markChanged(
      mutations.map((row) =>
        row.id === id ? ({ ...row, ...patch } as ScenarioMutation) : row
      )
    );
  const removeRow = (id: string) => markChanged(mutations.filter((row) => row.id !== id));

  const evaluate = async () => {
    if (!valid || evaluating) return;
    setEvaluating(true);
    setMessage(null);
    try {
      await runScenario(overlay, { name: name || "Decision", horizonDays });
      setEvaluatedSignature(signature);
      setMessage("Decision evaluated for the selected horizon.");
    } catch {
      setMessage("Could not evaluate this decision. Review the assumptions and try again.");
    } finally {
      setEvaluating(false);
    }
  };

  const save = async () => {
    if (!valid || stale || evaluating || saving) return;
    setSaving(true);
    try {
      if (scenarioId != null) {
        await updateScenario(scenarioId, name || "Decision", overlay);
        onSaved?.(scenarioId);
      } else {
        const created = await createScenario(name || "Decision", overlay);
        onSaved?.(created.id);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="relative overflow-hidden">
      <div className="text-gold/40"><GuillocheBand height={14} waves={4} seed={5} /></div>
      <CardContent className="space-y-5 p-5 sm:p-6">
        <div>
          <h2 className="font-sans text-lg font-semibold">What do you want to test?</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Choose a common decision, enter the amount and date, then evaluate it over {horizonDays} days.
          </p>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="Decision shortcuts">
          <Button type="button" variant="outline" className="min-h-11" onClick={() => addRow("oneoff", "expense")}>One-time purchase</Button>
          <Button type="button" variant="outline" className="min-h-11" onClick={() => addRow("oneoff", "income")}>One-time income</Button>
          <Button type="button" variant="outline" className="min-h-11" onClick={() => addRow("expense")}>New recurring expense</Button>
          <Button type="button" variant="outline" className="min-h-11" onClick={() => addRow("income")}>New recurring income</Button>
        </div>

        <details className="border-y border-rule py-3">
          <summary className="cursor-pointer font-sans text-sm font-semibold">Advanced assumptions</summary>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" size="sm" className="min-h-11" variant="outline" onClick={() => addRow("goal")}>+ Goal change</Button>
            <Button type="button" size="sm" className="min-h-11" variant="outline" disabled={hasBalanceOverride} onClick={() => addRow("balance")}>+ Starting balance</Button>
          </div>
        </details>

        {mutations.length === 0 ? (
          <p className="py-5 text-center text-sm text-muted-foreground">
            Choose a decision above. Nothing is saved or moved when you evaluate it.
          </p>
        ) : (
          <ul className="space-y-3">
            {mutations.map((mutation) => (
              <li key={mutation.id} data-testid="scenario-row" className="ledger-row py-3">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <MutationStamp mutation={mutation} />
                  <Button type="button" variant="ghost" size="sm" className="min-h-11" aria-label="Remove assumption" onClick={() => removeRow(mutation.id)}>Remove</Button>
                </div>
                <MutationEditor
                  mutation={mutation}
                  goals={goals}
                  horizonStart={horizonStart}
                  horizonEnd={horizonEnd}
                  onChange={(patch) => patchRow(mutation.id, patch)}
                />
                {errors.get(mutation.id)?.map((error) => (
                  <p key={error} className="mt-2 text-sm text-debit" role="alert">{error}</p>
                ))}
              </li>
            ))}
          </ul>
        )}

        <div className="grid gap-3 border-t border-rule pt-4 sm:grid-cols-[1fr_auto_auto] sm:items-end">
          <Field label="Decision name" htmlFor="scenario-name">
            <Input id="scenario-name" value={name} placeholder="e.g. Replace my laptop" maxLength={200} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Button type="button" className="min-h-11" disabled={!valid || evaluating} onClick={evaluate}>
            {evaluating ? "Evaluating…" : "Evaluate decision"}
          </Button>
          <Button type="button" variant="outline" className="min-h-11" disabled={!valid || stale || evaluating || saving} onClick={save}>
            {saving ? "Saving…" : scenarioId != null ? "Update saved decision" : "Save decision"}
          </Button>
        </div>
        <p className="min-h-5 text-sm text-muted-foreground" aria-live="polite">{message}</p>
      </CardContent>
    </Card>
  );
}

function MutationStamp({ mutation }: { mutation: ScenarioMutation }) {
  const credit = mutation.kind === "income" || (mutation.kind === "oneoff" && mutation.flowKind === "income") || mutation.kind === "balance";
  const label = mutation.kind === "oneoff"
    ? mutation.flowKind === "income" ? "One-time income" : "One-time purchase"
    : KIND_LABELS[mutation.kind] ?? "Assumption";
  return <Stamp variant={credit ? "credit" : "debit"} still>{label}</Stamp>;
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label htmlFor={htmlFor} className="font-sans text-xs font-semibold text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}

function MutationEditor({ mutation: m, goals, horizonStart, horizonEnd, onChange }: {
  mutation: ScenarioMutation;
  goals: { id?: number; name: string }[];
  horizonStart: string;
  horizonEnd: string;
  onChange: (patch: Partial<ScenarioMutation>) => void;
}) {
  if (m.kind === "income" || m.kind === "expense") {
    return (
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Description" htmlFor={`${m.id}-title`}><Input id={`${m.id}-title`} value={m.title} placeholder={m.kind === "income" ? "Side income" : "Membership"} onChange={(e) => onChange({ title: e.target.value })} /></Field>
        <Field label="Amount" htmlFor={`${m.id}-amount`}><Input id={`${m.id}-amount`} type="number" min="0.01" step="0.01" value={m.amount || ""} onChange={(e) => onChange({ amount: Number(e.target.value) })} /></Field>
        <Field label="Repeats" htmlFor={`${m.id}-recurrence`}>
          <Select value={m.recurrence} onValueChange={(value) => onChange({ recurrence: value })}>
            <SelectTrigger id={`${m.id}-recurrence`}><SelectValue /></SelectTrigger>
            <SelectContent>{RECURRENCES.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      </div>
    );
  }
  if (m.kind === "oneoff") {
    return (
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Description" htmlFor={`${m.id}-title`}><Input id={`${m.id}-title`} value={m.title} onChange={(e) => onChange({ title: e.target.value })} /></Field>
        <Field label="Amount" htmlFor={`${m.id}-amount`}><Input id={`${m.id}-amount`} type="number" min="0.01" step="0.01" value={m.amount || ""} onChange={(e) => onChange({ amount: Number(e.target.value) })} /></Field>
        <Field label="Date" htmlFor={`${m.id}-date`}><Input id={`${m.id}-date`} type="date" min={horizonStart} max={horizonEnd} value={m.date} onChange={(e) => onChange({ date: e.target.value })} /></Field>
      </div>
    );
  }
  if (m.kind === "goal") {
    return (
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Goal" htmlFor={`${m.id}-goal`}>
          <Select value={m.goalId ? String(m.goalId) : ""} onValueChange={(v) => onChange({ goalId: Number(v) })}>
            <SelectTrigger id={`${m.id}-goal`}><SelectValue placeholder="Choose a goal" /></SelectTrigger>
            <SelectContent>{goals.filter((g) => g.id != null).map((g) => <SelectItem key={g.id} value={String(g.id)}>{g.name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="New target amount" htmlFor={`${m.id}-amount`}><Input id={`${m.id}-amount`} type="number" min="0.01" step="0.01" value={m.amount ?? ""} onChange={(e) => onChange({ amount: e.target.value === "" ? undefined : Number(e.target.value) })} /></Field>
        <Field label="New target date" htmlFor={`${m.id}-target-date`}><Input id={`${m.id}-target-date`} type="date" value={m.targetDate ?? ""} onChange={(e) => onChange({ targetDate: e.target.value || undefined })} /></Field>
      </div>
    );
  }
  if (m.kind === "balance") {
    return <Field label="Starting balance (may be negative)" htmlFor={`${m.id}-balance`}><Input id={`${m.id}-balance`} type="number" step="0.01" value={m.amount} onChange={(e) => onChange({ amount: Number(e.target.value) })} /></Field>;
  }
  return null;
}

function validateMutations(mutations: ScenarioMutation[]): Map<string, string[]> {
  const errors = new Map<string, string[]>();
  const add = (id: string, message: string) => errors.set(id, [...(errors.get(id) ?? []), message]);
  const balanceRows = mutations.filter((mutation) => mutation.kind === "balance");
  if (balanceRows.length > 1) {
    balanceRows.forEach((row) => add(row.id, "Use only one starting-balance assumption."));
  }
  const goalRows = new Map<number, string[]>();
  for (const mutation of mutations) {
    if (mutation.kind === "goal" && mutation.goalId > 0) {
      goalRows.set(mutation.goalId, [...(goalRows.get(mutation.goalId) ?? []), mutation.id]);
    }
  }
  for (const ids of goalRows.values()) {
    if (ids.length > 1) ids.forEach((id) => add(id, "Change each goal only once per decision."));
  }
  for (const m of mutations) {
    if (m.kind === "income" || m.kind === "expense") {
      if (!m.title.trim()) add(m.id, "Enter a description.");
      if (!Number.isFinite(m.amount) || m.amount <= 0) add(m.id, "Amount must be greater than zero.");
      if (!RECURRENCES.includes(m.recurrence)) add(m.id, "Choose a supported recurrence.");
    } else if (m.kind === "oneoff") {
      if (!Number.isFinite(m.amount) || m.amount <= 0) add(m.id, "Amount must be greater than zero.");
      if (!m.date) add(m.id, "Choose a date inside the selected horizon.");
    } else if (m.kind === "goal") {
      if (m.goalId <= 0) add(m.id, "Choose a goal.");
      if (m.amount == null && !m.targetDate && m.progress == null) add(m.id, "Enter at least one goal change.");
      if (m.amount != null && (!Number.isFinite(m.amount) || m.amount <= 0)) add(m.id, "Goal target must be greater than zero.");
    } else if (m.kind === "balance" && !Number.isFinite(m.amount)) {
      add(m.id, "Enter a valid starting balance.");
    } else if (m.kind === "config") {
      add(m.id, "Settings are not supported in decision evaluation.");
    }
  }
  return errors;
}
