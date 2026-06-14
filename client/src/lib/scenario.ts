/**
 * Fold a stacked list of {@link ScenarioMutation} draft rows into the dollar
 * overlay the API accepts ({@link ScenarioMutationPayload}). Pure — no I/O — so
 * the builder and its tests share one mapping (v6 doc 07).
 */
import type {
  ScenarioMutation,
  ScenarioMutationPayload,
} from "@/types";

export function toOverlayPayload(
  mutations: ScenarioMutation[]
): ScenarioMutationPayload {
  const payload: ScenarioMutationPayload = {
    added_recurring: [],
    excluded_source_ids: [],
    overridden_recurring: [],
    discrete_flows: [],
    goal_mutations: [],
    config_overrides: {},
    balance_override: null,
  };

  for (const m of mutations) {
    switch (m.kind) {
      case "income":
      case "expense":
        payload.added_recurring.push({
          title: m.title || (m.kind === "income" ? "Income" : "Expense"),
          amount: m.amount,
          recurrence: m.recurrence,
          kind: m.kind,
          category: m.category,
          anchor_date: m.anchorDate ?? null,
        });
        break;
      case "oneoff":
        payload.discrete_flows.push({
          date: m.date,
          amount: m.amount,
          kind: m.flowKind,
          title: m.title,
          category: m.category,
        });
        break;
      case "goal":
        payload.goal_mutations.push({
          goal_id: m.goalId,
          amount: m.amount ?? null,
          target_date: m.targetDate ?? null,
          progress: m.progress ?? null,
          name: m.name ?? null,
        });
        break;
      case "balance":
        // Last balance row wins (a single starting balance override).
        payload.balance_override = m.amount;
        break;
      case "config":
        payload.config_overrides[m.key] = m.value;
        break;
    }
  }

  return payload;
}

let _seq = 0;
/** A stable-enough unique id for a freshly-added builder row. */
export function newMutationId(): string {
  _seq += 1;
  return `m${_seq}`;
}

/** A blank draft row for a given kind, with sensible defaults. */
export function blankMutation(kind: ScenarioMutation["kind"]): ScenarioMutation {
  const id = newMutationId();
  switch (kind) {
    case "income":
      return { id, kind, title: "", amount: 0, recurrence: "monthly", category: "" };
    case "expense":
      return { id, kind, title: "", amount: 0, recurrence: "monthly", category: "" };
    case "oneoff":
      return { id, kind, title: "", amount: 0, date: "", flowKind: "expense", category: "" };
    case "goal":
      return { id, kind, goalId: 0, amount: undefined };
    case "balance":
      return { id, kind, amount: 0 };
    case "config":
      return { id, kind, key: "s2s_buffer_on", value: true };
  }
}
