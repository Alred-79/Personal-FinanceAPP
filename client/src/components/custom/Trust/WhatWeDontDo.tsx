import { cn } from "@/lib/utils";

/** The promises stated as negatives — each one enforced in code, not just policy. */
const PROMISES: { title: string; body: string }[] = [
  {
    title: "We don't move your money",
    body: "The bank connection is read-only — a read literally can't write. The assistant drafts a move; you execute it yourself, in your own bank.",
  },
  {
    title: "We don't sell your data",
    body: "No ad model, no broker on the other end. Your ledger is yours — that's how it stays free without you quietly becoming the product.",
  },
  {
    title: "We don't recommend products for a kickback",
    body: "No affiliate steering. A firewall keeps the assistant from pushing a card or loan it gets paid to push.",
  },
  {
    title: "We don't reward you for spending",
    body: "The game gives XP for real money wins — paying bills, funding goals — never for spending. You can't buy your way up.",
  },
];

/**
 * The "What we don't do" panel (docs/FRONTEND-REPOSITIONING §6) — the Plaid-distrust
 * and "you are the product" rebuttal, stated plainly. Each line is a guarantee the
 * codebase actually enforces, surfaced where a skeptical user can find it.
 */
export function WhatWeDontDo({ className }: { className?: string }) {
  return (
    <div className={cn("border border-rule-strong/35 bg-card p-5", className)}>
      <p className="dept-label text-gold">What we don&rsquo;t do</p>
      <h3 className="mt-1.5 font-display text-lg font-semibold">
        The lines we won&rsquo;t cross.
      </h3>
      <ul className="mt-4 grid gap-4 sm:grid-cols-2">
        {PROMISES.map((p) => (
          <li key={p.title} className="flex gap-2.5">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              className="mt-0.5 shrink-0 text-gold"
              aria-hidden
            >
              <path d="M20 6 9 17l-5-5" />
            </svg>
            <div className="min-w-0">
              <p className="font-display text-[0.98rem] font-semibold leading-snug">
                {p.title}
              </p>
              <p className="mt-1 text-[0.85rem] leading-relaxed text-muted-foreground">
                {p.body}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
