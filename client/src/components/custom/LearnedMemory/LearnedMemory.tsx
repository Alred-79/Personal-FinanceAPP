import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { CornerRosette } from "@/components/engraving/Guilloche";
import type { MemoryFact } from "@/types";

/* ──────────────────────────────────────────────────────────────────────────
 * WHAT THE CLERK REMEMBERS  (Pillar 1A — the transparency contract)
 *
 * The durable facts the assistant has learned about you, read into its prompt
 * each turn. This panel is the trust contract: nothing it remembers is hidden
 * or permanent — every fact is visible here with its source, and can be struck.
 * ────────────────────────────────────────────────────────────────────────── */

const SOURCE_META: Record<
  MemoryFact["source"],
  { label: string; glyph: string }
> = {
  user: { label: "You told me", glyph: "✶" },
  deterministic: { label: "Learned from your activity", glyph: "❧" },
  llm: { label: "Inferred", glyph: "❀" },
};

/** Turn a closed-enum key (incl. ``category_preference:Food``) into a label. */
function keyLabel(key: string): string {
  if (key.startsWith("category_preference:")) {
    return `Category preference · ${key.split(":", 2)[1]}`;
  }
  const map: Record<string, string> = {
    tone_preference: "Tone",
    savings_intent: "Savings goal",
    income_cadence: "Income cadence",
    recurring_note: "Recurring note",
    essential_category: "Essential category",
  };
  return map[key] ?? key;
}

export function LearnedMemory() {
  const { toast } = useToast();
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: MemoryFact[] }>("/memory/");
      setFacts(Array.isArray(data?.items) ? data.items : []);
    } catch {
      toast({ title: "Could not load what I've learned", variant: "destructive" });
    } finally {
      setLoaded(true);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const forget = async (fact: MemoryFact) => {
    if (!confirm(`Forget "${keyLabel(fact.key)}"?`)) return;
    try {
      await api.delete(`/memory/${encodeURIComponent(fact.key)}/`);
      toast({ title: "Forgotten" });
      refresh();
    } catch {
      toast({ title: "Could not forget that", variant: "destructive" });
    }
  };

  return (
    <section className="relative">
      <header className="plate relative overflow-hidden bg-card px-6 py-5">
        <div className="pointer-events-none absolute -right-5 -top-6 text-gold/15">
          <CornerRosette size={108} seed={41} />
        </div>
        <div className="relative flex items-center justify-between gap-4">
          <div>
            <p className="dept-label">Office of the Clerk</p>
            <h3 className="mt-1 font-display text-2xl leading-tight tracking-tight">
              What the Clerk Remembers
            </h3>
            <p className="mt-1 max-w-md text-sm text-muted-foreground">
              Facts I keep between conversations so I don't ask twice. You can see
              every one and strike any of them — nothing here is hidden or
              permanent.
            </p>
          </div>
          <div className="hidden shrink-0 text-right sm:block">
            <p className="intaglio text-4xl leading-none ledger-figures">
              {facts.length}
            </p>
            <p className="dept-label mt-1">on file</p>
          </div>
        </div>
      </header>

      <div className="mt-6 plate relative bg-card p-5">
        <div className="section-rule mb-2">
          <span className="dept-label whitespace-nowrap">The Record</span>
        </div>

        {!loaded ? (
          <p className="py-12 text-center font-sans italic text-muted-foreground">
            Reading the record…
          </p>
        ) : facts.length === 0 ? (
          <div className="grid place-items-center py-12 text-center">
            <div className="text-rule-strong/40">
              <CornerRosette size={64} seed={9} />
            </div>
            <p className="mt-3 font-display text-lg">Nothing on file yet</p>
            <p className="mt-1 max-w-xs text-sm text-muted-foreground">
              As you correct categories and tell me about your goals, I'll keep a
              note here — always visible, always yours to strike.
            </p>
          </div>
        ) : (
          <ul>
            {facts.map((fact, i) => {
              const meta = SOURCE_META[fact.source];
              return (
                <li
                  key={fact.key}
                  className="ledger-row animate-rise-in flex items-center gap-3 py-3"
                  style={{ animationDelay: `${Math.min(i, 6) * 50}ms` }}
                >
                  <span
                    className="grid h-8 w-8 shrink-0 place-items-center border border-rule text-gold"
                    aria-hidden
                  >
                    {meta.glyph}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-sans text-sm font-semibold">
                      {keyLabel(fact.key)}
                      {fact.pinned && (
                        <span className="ml-2 align-middle text-[10px] text-gold">
                          ★ pinned
                        </span>
                      )}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {fact.value}
                    </p>
                  </div>
                  <span className="hidden shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70 sm:inline">
                    {meta.label}
                  </span>
                  <button
                    onClick={() => forget(fact)}
                    aria-label="Forget this"
                    className={cn(
                      "shrink-0 font-mono text-xs text-muted-foreground transition-colors hover:text-debit"
                    )}
                  >
                    ✕
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
