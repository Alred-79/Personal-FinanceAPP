import { ReactNode } from "react";

/** The six "instruments" — the product's headline features, as banknote serials. */
export type Feature = { no: string; title: string; body: string; icon: ReactNode };

export const FEATURES: Feature[] = [
  {
    no: "No. 01",
    title: "The Clerk",
    body: "A chatbot that drafts the move — re-budget, schedule, reconcile — then hands you a diff plate to authorize. You ask; it proposes; you stamp. Nothing happens behind your back.",
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
  },
  {
    no: "No. 02",
    title: "Import Anything",
    body: "Snap a photo of a receipt, tax form, or check — or drop a messy statement or mystery CSV. The Detangler reads them, reconciles the duplicates, and hands back a clean register — no manual category roulette.",
    icon: <path d="M4 5h16M4 12h16M4 19h10" />,
  },
  {
    no: "No. 03",
    title: "Subscriptions Watch",
    body: "The recurring charges you forgot about, surfaced and dated. It catches silent price creep and the trials about to bill — so the small leaks stop draining the account.",
    icon: (
      <>
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 12a9 9 0 0 1-15 6.7L3 16" />
        <path d="M21 4v4h-4M3 20v-4h4" />
      </>
    ),
  },
  {
    no: "No. 04",
    title: "Nightly Auditor",
    body: "While you sleep, it reconciles the day, flags the odd charge, and leaves a short note in the margin. You wake up to an account already balanced.",
    icon: (
      <>
        <path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6Z" />
        <path d="M9 12l2 2 4-4" />
      </>
    ),
  },
  {
    no: "No. 05",
    title: "The Expedition",
    body: "Paying down debt and chasing goals, charted as a voyage with bosses to fell and ground to claim. Progress you can see — the dull parts of finance, finally worth playing.",
    icon: (
      <>
        <path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6Z" />
        <path d="M12 7v4l2.5 1.5" />
        <path d="M9.5 9.5h5" />
      </>
    ),
  },
  {
    no: "No. 06",
    title: "Tax, Filed Quietly",
    body: "1099s, deductions, quarterly estimates — tracked all year and stamped into a packet at season's end. The dread becomes a form you just sign.",
    icon: (
      <>
        <rect x="4" y="4" width="16" height="16" />
        <path d="M8 9h8M8 13h5" />
      </>
    ),
  },
];
