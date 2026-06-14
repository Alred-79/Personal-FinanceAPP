import { useEffect, useMemo, useRef, useState } from "react";
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
import { SectionRule } from "@/components/engraving/SectionRule";
import { GuillocheBand } from "@/components/engraving/Guilloche";
import {
  blankMutation,
  toOverlayPayload,
} from "@/lib/scenario";
import type { ScenarioMutation, ScenarioMutationKind } from "@/types";

const KIND_LABELS: Record<ScenarioMutationKind, string> = {
  income: "Recurring income",
  expense: "Recurring expense",
  oneoff: "One-off flow",
  goal: "Goal change",
  balance: "Starting balance",
  config: "Setting",
};

const RECURRENCES = ["weekly", "bi-weekly", "monthly", "quarterly", "annually"];

/**
 * The stacked what-if builder (v6 doc 07): a list of editable hypothetical rows
 * (income / expense / one-off / goal / balance / config), a name + Save, and a
 * debounced live evaluate so the Forecast overlay updates as you type.
 */
export default function ScenarioBuilder({
  initialMutations,
  initialName,
  scenarioId,
  onSaved,
}: {
  initialMutations?: ScenarioMutation[];
  initialName?: string;
  /** When set, Save updates this scenario instead of creating a new one. */
  scenarioId?: number;
  onSaved?: (id: number) => void;
}) {
  const goals = useStore((s) => s.goals);
  const runScenario = useStore((s) => s.runScenario);
  const createScenario = useStore((s) => s.createScenario);
  const updateScenario = useStore((s) => s.updateScenario);

  const [name, setName] = useState(initialName ?? "");
  const [mutations, setMutations] = useState<ScenarioMutation[]>(
    initialMutations ?? []
  );
  const [saving, setSaving] = useState(false);

  // Re-seed when a deep link changes the initial rows (e.g. ?goal=<id>).
  useEffect(() => {
    if (initialMutations) setMutations(initialMutations);
    if (initialName !== undefined) setName(initialName);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialMutations, initialName]);

  const overlay = useMemo(() => toOverlayPayload(mutations), [mutations]);

  // Debounced live run: every edit schedules an evaluate ~400ms later, and the
  // store aborts any in-flight run so only the freshest overlay's diff lands.
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    if (mutations.length === 0) return;
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runScenario(overlay, { name: name || "Scenario" });
    }, 400);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay]);

  const addRow = (kind: ScenarioMutationKind) =>
    setMutations((rows) => [...rows, blankMutation(kind)]);

  const removeRow = (id: string) =>
    setMutations((rows) => rows.filter((r) => r.id !== id));

  const patchRow = (id: string, patch: Partial<ScenarioMutation>) =>
    setMutations((rows) =>
      rows.map((r) => (r.id === id ? ({ ...r, ...patch } as ScenarioMutation) : r))
    );

  const save = async () => {
    setSaving(true);
    try {
      if (scenarioId != null) {
        await updateScenario(scenarioId, name || "Scenario", overlay);
        onSaved?.(scenarioId);
      } else {
        const created = await createScenario(name || "Scenario", overlay);
        onSaved?.(created.id);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="relative overflow-hidden animate-ink-in">
      <div className="text-gold/40">
        <GuillocheBand height={14} waves={4} seed={5} />
      </div>
      <CardContent className="space-y-5 p-6">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[180px] space-y-1.5">
            <label
              htmlFor="scenario-name"
              className="font-sans text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
            >
              Scenario name
            </label>
            <Input
              id="scenario-name"
              aria-label="Scenario name"
              value={name}
              placeholder="e.g. Aggressive savings"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <Button onClick={save} disabled={saving} aria-label="Save scenario">
            {saving ? "Saving…" : scenarioId != null ? "Update" : "Save"}
          </Button>
        </div>

        <SectionRule fleuron>Hypotheticals</SectionRule>

        {mutations.length === 0 ? (
          <p className="py-4 text-center font-sans text-sm italic text-muted-foreground">
            Stack a change below to project a what-if.
          </p>
        ) : (
          <ul className="space-y-2.5">
            {mutations.map((m) => (
              <li
                key={m.id}
                data-testid="scenario-row"
                className="ledger-row flex flex-wrap items-center gap-2 py-2"
              >
                <MutationStamp kind={m.kind} mutation={m} />
                <MutationEditor
                  mutation={m}
                  goals={goals}
                  onChange={(patch) => patchRow(m.id, patch)}
                />
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Remove row"
                  onClick={() => removeRow(m.id)}
                >
                  ✕
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(KIND_LABELS) as ScenarioMutationKind[]).map((k) => (
            <Button
              key={k}
              size="sm"
              variant="outline"
              onClick={() => addRow(k)}
            >
              + {KIND_LABELS[k]}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function MutationStamp({
  kind,
  mutation,
}: {
  kind: ScenarioMutationKind;
  mutation: ScenarioMutation;
}) {
  // Credit (money in) vs debit (money out) tint for the eye.
  const isCredit =
    kind === "income" ||
    (kind === "oneoff" && mutation.kind === "oneoff" && mutation.flowKind === "income") ||
    kind === "balance";
  return (
    <Stamp variant={isCredit ? "credit" : "debit"} still>
      {KIND_LABELS[kind]}
    </Stamp>
  );
}

function MutationEditor({
  mutation,
  goals,
  onChange,
}: {
  mutation: ScenarioMutation;
  goals: { id?: number; name: string }[];
  onChange: (patch: Partial<ScenarioMutation>) => void;
}) {
  const m = mutation;
  if (m.kind === "income" || m.kind === "expense") {
    return (
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <Input
          aria-label="Title"
          className="w-36"
          value={m.title}
          placeholder="Title"
          onChange={(e) => onChange({ title: e.target.value })}
        />
        <Input
          aria-label="Amount"
          className="w-28"
          type="number"
          value={m.amount}
          onChange={(e) => onChange({ amount: Number(e.target.value) })}
        />
        <Select
          value={m.recurrence}
          onValueChange={(v) => onChange({ recurrence: v })}
        >
          <SelectTrigger className="w-32" aria-label="Recurrence">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RECURRENCES.map((r) => (
              <SelectItem key={r} value={r}>
                {r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }
  if (m.kind === "oneoff") {
    return (
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <Input
          aria-label="Title"
          className="w-36"
          value={m.title}
          placeholder="Title"
          onChange={(e) => onChange({ title: e.target.value })}
        />
        <Input
          aria-label="Amount"
          className="w-28"
          type="number"
          value={m.amount}
          onChange={(e) => onChange({ amount: Number(e.target.value) })}
        />
        <Input
          aria-label="Date"
          className="w-40"
          type="date"
          value={m.date}
          onChange={(e) => onChange({ date: e.target.value })}
        />
        <Select
          value={m.flowKind}
          onValueChange={(v) => onChange({ flowKind: v as "income" | "expense" })}
        >
          <SelectTrigger className="w-28" aria-label="Flow kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="expense">expense</SelectItem>
            <SelectItem value="income">income</SelectItem>
          </SelectContent>
        </Select>
      </div>
    );
  }
  if (m.kind === "goal") {
    return (
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <Select
          value={m.goalId ? String(m.goalId) : ""}
          onValueChange={(v) => onChange({ goalId: Number(v) })}
        >
          <SelectTrigger className="w-44" aria-label="Goal">
            <SelectValue placeholder="Choose a goal" />
          </SelectTrigger>
          <SelectContent>
            {goals
              .filter((g) => g.id != null)
              .map((g) => (
                <SelectItem key={g.id} value={String(g.id)}>
                  {g.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <Input
          aria-label="Target amount"
          className="w-32"
          type="number"
          placeholder="Target $"
          value={m.amount ?? ""}
          onChange={(e) =>
            onChange({ amount: e.target.value === "" ? undefined : Number(e.target.value) })
          }
        />
        <Input
          aria-label="Target date"
          className="w-40"
          type="date"
          value={m.targetDate ?? ""}
          onChange={(e) => onChange({ targetDate: e.target.value || undefined })}
        />
      </div>
    );
  }
  if (m.kind === "balance") {
    return (
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <Input
          aria-label="Starting balance"
          className="w-36"
          type="number"
          value={m.amount}
          onChange={(e) => onChange({ amount: Number(e.target.value) })}
        />
      </div>
    );
  }
  if (m.kind === "config") {
    return (
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <Input
          aria-label="Setting key"
          className="w-44"
          value={m.key}
          onChange={(e) => onChange({ key: e.target.value })}
        />
        <Select
          value={m.value ? "true" : "false"}
          onValueChange={(v) => onChange({ value: v === "true" })}
        >
          <SelectTrigger className="w-24" aria-label="Setting value">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true">on</SelectItem>
            <SelectItem value="false">off</SelectItem>
          </SelectContent>
        </Select>
      </div>
    );
  }
  return null;
}
