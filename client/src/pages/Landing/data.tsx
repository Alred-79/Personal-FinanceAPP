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
    title: "Import Anything",
    body: "Snap a photo of a receipt, tax form, or check — or drop a messy statement or mystery CSV. The Detangler reads them, reconciles the duplicates, and hands back a clean register — no manual category roulette.",
    icon: <path d="M4 5h16M4 12h16M4 19h10" />,
  },
  {
    no: "No. 02",
    title: "The Clerk",
    body: "An assistant that drafts the move — re-budget, schedule, set money aside, draft a payment — then hands you a diff plate to authorize. You ask; it proposes; you stamp. It can read your transactions and draft actions; it can't move money or see full account numbers.",
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
    body: "The recurring charges you forgot about, surfaced and dated. It flags the trials about to bill — and, once it's seen a few repeat merchants, spots a subscription quietly creeping up in price. The small leaks stop draining the account.",
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
    body: "Paying down debt and funding goals, charted as a voyage with bosses to fell and ground to claim. You earn progress for real money wins — never for spending. The dull parts of finance, finally worth playing.",
    icon: (
      <>
        <path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6Z" />
        <path d="M12 7v4l2.5 1.5" />
        <path d="M9.5 9.5h5" />
      </>
    ),
    gated: true,
    gatedNote: "The game layer starts off — flip it on (ambient or full) in Settings whenever you want it.",
  },
  {
    no: "No. 05",
    title: "Tax, tracked all year",
    body: "1099s, deductions, and your quarterly estimate — tracked from January, not scrambled in April. We estimate what you'll owe and help you set it aside in a reserve you fund, so the bill isn't a surprise. The dread becomes a form you just sign.",
    icon: (
      <>
        <rect x="4" y="4" width="16" height="16" />
        <path d="M8 9h8M8 13h5" />
      </>
    ),
    gated: true,
    gatedNote: "The tax desk switches on per workspace (and when you tell us you're self-employed).",
  },
  {
    no: "No. 06",
    title: "Nightly Auditor",
    body: "While you sleep, it reconciles the day, flags the odd charge, and leaves a short note in the margin. You wake up to an account already balanced.",
    icon: (
      <>
        <path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6Z" />
        <path d="M9 12l2 2 4-4" />
      </>
    ),
    gated: true,
    gatedNote: "An opt-in background job — off until your workspace turns it on.",
  },
];
