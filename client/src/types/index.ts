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
  }) => void;
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