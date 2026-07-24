import { ReactNode } from "react";

/** The six "instruments" — the product's headline features, as banknote serials.
 *  `gated` marks a feature that ships OFF by default (instance flag or per-user
 *  opt-in); the UI tags it honestly instead of implying every user has it. */
export type Feature = {
  no: string;
  title: string;
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
    title: "Bring the Whole Picture",
    body: "Connect your accounts or drop in receipts, statements, and messy CSVs. The Ledger reconciles duplicates and brings bills, income, and transactions into one register — so one bank never tells only part of the story.",
    icon: <path d="M4 5h16M4 12h16M4 19h10" />,
  },
  {
    no: "No. 02",
    title: "The Clerk",
    body: "Ask a question in plain language and get an answer grounded in your ledger. The Clerk can draft a budget change, schedule, or allocation, then hands you the exact difference to review. It proposes; only you confirm.",
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
  },
  {
    no: "No. 03",
    title: "Subscriptions Watch",
    body: "See recurring charges across accounts in one place. The Ledger groups their cadence, shows recorded price changes, and separates likely-active charges from items that need your review.",
    icon: (
      <>
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 12a9 9 0 0 1-15 6.7L3 16" />
        <path d="M21 4v4h-4M3 20v-4h4" />
      </>
    ),
  },
  {
    no: "No. 04",
    title: "The Expedition",
    body: "Turn debt payoff and goal funding into visible progress when that helps. The optional game layer rewards real money wins — never spending — and always keeps the actual figures in view.",
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
    title: "Work Money, When Needed",
    body: "Freelance, contract, commission, and mixed income tools stay available as an optional layer. Track uneven income, deductions, and a tax-reserve target you fund in your own bank without making work define the whole app.",
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
    title: "A Quiet Second Look",
    body: "The nightly review reconciles the day, flags an unusual charge, and leaves a short note in the margin. Important changes surface without turning money into a stream of alerts.",
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
