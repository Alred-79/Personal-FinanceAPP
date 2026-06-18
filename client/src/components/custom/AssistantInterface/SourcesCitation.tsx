import { useState } from "react";
import { ChevronDown, ChevronRight, ReceiptText } from "lucide-react";
import { AssistantSources } from "@/types";

/**
 * W2 — "Cite sources" (verifiable AI). Shown under an assistant figure when the
 * Clerk grounded its answer in real transaction rows. The label makes the
 * anti-hallucination architecture visible — "based on these N transactions" —
 * and expands to the exact rows (title · date · amount) the engine read. When
 * the tool truncated its output the count reads "based on N of M". A turn with
 * no read tool carries no sources, so this never renders for pure chat.
 */
export function SourcesCitation({ sources }: { sources: AssistantSources }) {
  const [open, setOpen] = useState(false);
  const { data, count, total, capped } = sources;
  if (!count) return null;

  const noun = total === 1 ? "transaction" : "transactions";
  const label = capped
    ? `Based on ${count} of ${total} ${noun}`
    : `Based on ${count} ${noun}`;

  return (
    <div className="mt-1.5 text-xs text-muted-foreground" data-testid="sources-citation">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded px-1 py-0.5 hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-3 w-3" aria-hidden />
        ) : (
          <ChevronRight className="h-3 w-3" aria-hidden />
        )}
        <ReceiptText className="h-3 w-3" aria-hidden />
        <span>{label}</span>
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 border-l border-border pl-3" data-testid="sources-list">
          {data.map((row, i) => (
            <li key={row.id ?? i} className="flex items-baseline justify-between gap-3">
              <span className="truncate">{row.title ?? "Transaction"}</span>
              <span className="shrink-0 tabular-nums">
                {row.date ?? ""}
                {row.amount != null ? ` · $${Math.abs(row.amount).toFixed(2)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default SourcesCitation;
