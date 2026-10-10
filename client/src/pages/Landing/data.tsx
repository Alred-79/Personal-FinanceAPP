import { ReactNode } from "react";

/** The six "instruments" — the product's headline features, as banknote serials.
 *  `gated` marks a feature that ships OFF by default (instance flag or per-user
 *  opt-in); the UI tags it honestly instead of implying every user has it. */
export type Feature = {
  no: string;
  /** Plain-language title: what it does for you. */
  title: string;
  /** The product's own name for it, shown small, when it has one. */
  name?: string;
  body: string;
  icon: ReactNode;
  gated?: boolean;
  gatedNote?: string;
};

// Order is paired by index with SCENES in instrumentVisuals.tsx — keep them in
// lockstep. Sequence: Import → Clerk → Subscriptions → Expedition → Tax → Auditor.
export const FEATURES: Feature[] = [
  {
    no: "No. 01",
    title: "Every account in one register",
    body: "Connect your banks, or drop in statements, receipts, and messy CSVs. Duplicates are reconciled, so the number counts every bill and paycheck exactly once.",
    icon: <path d="M4 5h16M4 12h16M4 19h10" />,
  },
  {
    no: "No. 02",
    title: "Ask about your money in plain English",
    name: "The Clerk",
    body: "Ask “can I afford a $600 flight?” and get an answer grounded in your ledger. When it suggests a change, it shows you the exact difference first. It proposes; only you confirm.",
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
  },
  {
    no: "No. 03",
    title: "Catch subscriptions that creep up",
    name: "Subscriptions Watch",
    body: "Every recurring charge across your accounts in one list, with recorded price changes and the ones that need a second look.",
    icon: (
      <>
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 12a9 9 0 0 1-15 6.7L3 16" />
        <path d="M21 4v4h-4M3 20v-4h4" />
      </>
    ),
  },
  {
    no: "No. 04",
    title: "Make debt payoff feel like progress",
    name: "The Expedition",
    body: "An optional game layer that rewards real wins, like a paid-down card, and never rewards spending. The actual figures always stay in view.",
    icon: (
      <>
        <path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6Z" />
        <path d="M12 7v4l2.5 1.5" />
        <path d="M9.5 9.5h5" />
      </>
    ),
    gated: true,
    gatedNote: "Focus Mode starts off — turn it on in Settings whenever visible progress would help.",
  },
  {
    no: "No. 05",
    title: "Freelance income and taxes",
    name: "Work Money",
    body: "For uneven or self-employed income: track deductions and a tax-reserve target you fund in your own bank. It stays out of the way unless you need it.",
    icon: (
      <>
        <rect x="4" y="4" width="16" height="16" />
        <path d="M8 9h8M8 13h5" />
      </>
    ),
    gated: true,
    gatedNote: "The Work Money layer switches on only when uneven income or taxes are part of your picture.",
  },
  {
    no: "No. 06",
    title: "A nightly check for odd charges",
    name: "A Quiet Second Look",
    body: "An overnight review reconciles the day and flags an unusual charge with a short note in the margin. No stream of alerts.",
    icon: (
      <>
        <path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6Z" />
        <path d="M9 12l2 2 4-4" />
      </>
    ),
    gated: true,
    gatedNote: "An optional background review — off until you choose to turn it on.",
  },
];
