import type { ReactNode } from "react";

/** Recurrence cadence shared by transactions, expenses, and dialog forms. */
export type Frequency =
  | "daily"
  | "weekly"
  | "bi-weekly"
  | "monthly"
  | "quarterly"
  | "annually";

export interface Transaction {
  id: number;
  title: string;
  date: string;
  amount: number;
  category: string;
  type: "income" | "expense";
  backgroundColor?: string;
  frequency?: Frequency;
}

export interface Expense {
  id: number;
  title: string;
  amount: number;
  date: string;
  category: string;
  recurrence?: Frequency;
}

export interface DayCheckboxProps {
  value: string;
  selected?: boolean;
  onChange: (value: string, isSelected: boolean) => void;
}

export interface AggregatedData {
  date: string;
  income: number;
  expenses: number;
}

export interface Account {
  id: number;
  name: string;
  type: string;
  balance: number;
  last_updated: string;
  transactions?: Transaction[];
}

/** A line item pulled off a scanned receipt. Mirrors the server's ReceiptLineItem. */
export interface ReceiptLineItem {
  description?: string | null;
  amount?: number | null;
}

/**
 * Fields extracted from a receipt image by the vision endpoint
 * (`POST /receipts/scan/`). Nothing is persisted — this only prefills the
 * transaction form. Mirrors the server's ReceiptDraft model.
 */
export interface ReceiptDraft {
  merchant?: string | null;
  title?: string | null;
  amount?: number | null;
  date?: string | null;
  category?: string | null;
  line_items?: ReceiptLineItem[];
}

export interface TransactionDialogProps {
  onSubmit: (transaction: {
    title: string;
    amount: number;
    date: string;
    category: string;
    isIncome: boolean;
    account_id: number;
    recurrence?: Frequency;
    // May be async: the dialog awaits it and only closes/clears on success.
  }) => void | Promise<void>;
  /** Controlled open state. When omitted the dialog manages its own state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Prefill the form (e.g. from a scanned receipt) when the dialog opens. */
  initialDraft?: ReceiptDraft | null;
  /** Override the default "New Transaction" trigger button. */
  trigger?: ReactNode;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
}

// Notifications and subscriptions
export interface Notification {
  id: number;
  type: "budget_overrun" | "anomaly" | string;
  title: string;
  message: string;
  read: boolean;
  created_at: string | null;
}

export interface Subscription {
  merchant: string;
  title: string;
  amount: number;
  cadence: string;
  occurrences: number;
  last_date: string;
  next_date: string | null;
}

export interface ActionMessage {
  id: number;
  text: string;
  timestamp: number;
}

// ───────────────────────────────────────────────────────────────────────────
// Forecast + scenarios (v6).
//
// ``ForecastPoint`` lives here (not in store.ts) so the scenario types below can
// reuse it without a store→types→store import cycle; store.ts re-exports it for
// its existing consumers. Money is dollar floats on the client; the API boundary
// converts to/from cents.
// ───────────────────────────────────────────────────────────────────────────

export interface ForecastPoint {
  date: string;
  balance: number;
  change: number;
  income?: number;
  expenses?: number;
  label: string;
}

/** The kinds of hypothetical a scenario can stack. */
export type ScenarioMutationKind =
  | "income"
  | "expense"
  | "oneoff"
  | "goal"
  | "balance"
  | "config";

/**
 * One row in the stacked builder, a discriminated union on ``kind``. Each row is
 * an editable, dollar-denominated draft; {@link toOverlayPayload} folds the list
 * into the API's {@link ScenarioMutationPayload}.
 */
export type ScenarioMutation =
  | {
      id: string;
      kind: "income" | "expense";
      title: string;
      amount: number;
      recurrence: string;
      category?: string;
      anchorDate?: string;
    }
  | {
      id: string;
      kind: "oneoff";
      title: string;
      amount: number;
      date: string;
      flowKind: "income" | "expense";
      category?: string;
    }
  | {
      id: string;
      kind: "goal";
      goalId: number;
      amount?: number;
      targetDate?: string;
      progress?: number;
      name?: string;
    }
  | {
      id: string;
      kind: "balance";
      amount: number;
    }
  | {
      id: string;
      kind: "config";
      key: string;
      value: boolean;
    };

/** The dollar overlay the API accepts (`ScenarioOverlayIn` on the server). */
export interface ScenarioMutationPayload {
  added_recurring: Array<{
    title: string;
    amount: number;
    recurrence: string;
    kind: "income" | "expense";
    category?: string;
    anchor_date?: string | null;
  }>;
  excluded_source_ids: Array<[string, number]>;
  overridden_recurring: Array<{
    source_id: number;
    kind: "income" | "expense";
    amount?: number | null;
    recurrence?: string | null;
  }>;
  discrete_flows: Array<{
    date: string;
    amount: number;
    kind: "income" | "expense";
    title?: string;
    category?: string;
  }>;
  goal_mutations: Array<{
    goal_id: number;
    amount?: number | null;
    target_date?: string | null;
    progress?: number | null;
    name?: string | null;
  }>;
  balance_override?: number | null;
  config_overrides: Record<string, unknown>;
}

/** A saved scenario as returned by `GET /scenarios/` (dollar overlay). */
export interface Scenario {
  id: number;
  name: string;
  overlay: ScenarioMutationPayload;
  created_at: string | null;
  updated_at: string | null;
}

/** The metric set for one column of an evaluate/compare run (dollars). */
export interface ScenarioResult {
  overdraft_probability: number;
  lowest_balance: number;
  ending_balance: number;
  safe_to_spend: number;
  runway_days: number;
  goal_reach: Record<string, { reaches_on: string | null }>;
  /** Present on the forecast-backed columns; reused for the chart overlay. */
  timeline?: ForecastPoint[];
  trough_band?: { low: number; median: number; high: number };
}

/** Scenario − baseline, the shape `_diff` emits server-side (dollars / raw). */
export interface ScenarioDelta {
  overdraft_probability: number;
  lowest_balance: number;
  ending_balance: number;
  safe_to_spend: number;
  runway_days: number;
  goal_reach: Record<string, { reaches_on: string | null; delta_days: number | null }>;
}

/** A baseline-vs-scenario evaluate run (`POST /scenarios/{id}/evaluate/`). */
export interface ScenarioDiff {
  baseline: { name: string; result: ScenarioResult };
  scenario: {
    name: string;
    scenario_id: number | null;
    result: ScenarioResult;
    delta: ScenarioDelta;
  };
}

/** One column of a compare run, plus the N-column wrapper. */
export interface ScenarioCompareColumn {
  name: string;
  scenario_id?: number;
  result: ScenarioResult;
  delta?: ScenarioDelta;
}

export interface ScenarioCompareResult {
  columns: ScenarioCompareColumn[];
}

/** The result of committing a scenario through propose→confirm. */
export interface CommittedPlan {
  plan_id: number;
  rule_ids: number[];
}

/** The assistant's ``proposal`` SSE frame (v6 doc 08): a what-if commit offer. */
export interface AssistantProposal {
  action: string;
  scenario_id?: number | null;
  summary: string;
  confirm_token: string;
  diff?: {
    ending_balance?: number;
    safe_to_spend?: number;
    overdraft_probability?: number;
    timeline?: ForecastPoint[];
  };
}