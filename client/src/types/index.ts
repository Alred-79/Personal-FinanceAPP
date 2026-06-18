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
  // F2: lifecycle snapshot, merged in when merchant_lifecycle is enabled.
  probability_alive?: number;
  lifecycle_status?: "active" | "lapsing" | "dormant";
  expected_purchases?: number;
  price_change_pct?: number; // fractional increase vs prior stable amount
  last_amount?: number;
  prev_amount?: number | null;
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

/**
 * The assistant's ``assisted_action`` SSE frame (Pillar 2C — the Assisted Action
 * Bridge): a deduced real-world action the user executes in their own bank, which
 * the app verifies on the next sync. ``confirm_token`` creates the Bridge object
 * (it does NOT move money); ``bridge`` carries the display fields for the card.
 */
export interface AssistantBridge {
  action: string;
  summary: string;
  confirm_token: string;
  bridge: {
    kind: "transfer" | "bill_payment" | "goal_funding" | "tax_payment" | "debt_payment" | string;
    amount: number;
    rationale: string;
    source_ref?: string | null;
    dest_ref?: string | null;
    how?: {
      instruction?: string;
      deep_link?: string;
      goal_id?: number;
    };
  };
}

/** A fact the assistant has learned about the user (Pillar 1A). Mirrors the
 *  ``/memory/`` router payload. ``source`` records the trust lane. */
export interface MemoryFact {
  key: string;
  value: string;
  source: "user" | "deterministic" | "llm";
  confidence: number;
  pinned: boolean;
  updated_at: string;
}

// ── Messy-data ingestion (Reconciliation Desk / Import Anything) ────────────
// Mirror the backend Pydantic ImportSessionOut / ImportRowOut / BalanceCheckOut.
// Money is dollar floats; ``amount`` is signed (+ in / − out).

/** A row's review verdict, set by the extractor and editable by the user. */
export type ImportRowStatus =
  | "ok"
  | "duplicate"
  | "exception"
  | "needs_category"
  | "transfer_candidate";

/** One parsed line of an import session. */
export interface ImportRow {
  id: number;
  title: string;
  amount: number; // signed dollars
  date: string;
  category: string;
  running_balance?: number | null;
  status: ImportRowStatus;
  reason?: string | null;
  included: boolean;
  match_ref?: number | null;
}

/** The reconcile headline: does opening + Σtxns equal closing? */
export interface BalanceCheck {
  opening?: number | null;
  closing?: number | null;
  expected_delta?: number | null;
  actual_delta: number;
  discrepancy?: number | null;
  reconciled: boolean;
  exception_count: number;
}

/** A session plus its rows and balance check — the review payload. */
export interface ImportSession {
  id: number;
  account_id: number;
  source_kind: string; // pdf | image | text
  detected_kind?: string | null; // statement | feed | receipt | unknown
  status: "pending_review" | "committed" | "discarded";
  statement_period?: string | null;
  balance_check: BalanceCheck;
  rows: ImportRow[];
}

// ── Pillar 3 — tax & messy-data layer ────────────────────────────────────────
// Tax bucket is ORTHOGONAL to the 12 spend categories. Organization only — never
// an assertion that something is deductible.

/** One entry of the Schedule-C bucket registry (the dropdown source). */
export interface TaxBucket {
  key: string;
  label: string;
  irs_line: string;
  default_deductible_bps: number;
  kind: "expense" | "income";
}

/** A tax tag applied to a single transaction. */
export interface TaxTag {
  id: number;
  tx_type: "expense" | "income";
  tx_id: number;
  tax_year: number;
  bucket: string;
  bucket_label: string;
  irs_line: string;
  business_personal: "business" | "personal";
  deductible_bps: number;
  source: "user" | "rule" | "llm";
  note?: string | null;
}

export interface TaxDeductionLine {
  bucket: string;
  label: string;
  irs_line: string;
  total: number; // dollars
  deductible: number; // dollars
}

export interface TaxIncomeSource {
  issuer: string | null;
  form_type: string | null;
  income: number; // dollars
  withholding: number; // dollars
  provenance: "from_document" | "from_ledger";
}

/** The full tax-organization summary for a year (money in dollars). */
export interface TaxSummary {
  tax_year: number;
  income_by_source: {
    sources: TaxIncomeSource[];
    total_income: number;
    total_withholding: number;
  };
  deductions_by_bucket: TaxDeductionLine[];
  mileage: {
    miles: number;
    rate_cents_per_mile: number | null;
    deduction: number; // dollars
    rate_available: boolean;
  };
  estimated_quarterly: {
    tax_year: number;
    filing_status: string;
    total_income: number;
    wages: number;
    se_income: number;
    total_deductible: number;
    se_net_earnings: number;
    se_tax: number;
    income_tax: number;
    state_tax: number;
    taxable_base: number;
    total_withholding: number;
    payments_made: number;
    annual_estimate: number;
    remaining_estimate: number;
    per_quarter: number;
    safe_harbor_annual: number | null;
    safe_harbor_remaining: number | null;
    safe_harbor_per_quarter: number | null;
    due_dates: [string, string][];
    methodology: string;
    disclaimer: string;
  };
  disclaimer: string;
}

export type FilingStatus = "single" | "mfj" | "mfs" | "hoh";

export interface EstimateInputs {
  filing_status: FilingStatus;
  state_rate_pct: number;
  prior_year_tax: number | null;
  payments_made: number;
}

export interface MileageLog {
  id: number;
  trip_date: string;
  miles: number;
  purpose?: string | null;
  business_personal: "business" | "personal";
  tax_year: number;
}