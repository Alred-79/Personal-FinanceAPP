import { Stamp } from "@/components/engraving/Stamp";

const GRANTED = [
  "Accounts — names & balances",
  "Transactions — every debit & credit",
  "Budgets — envelopes, limits & pace",
  "Goals — targets & progress",
  "Context — a read-only snapshot",
];

const NEVER = ["Write a transaction", "Move or transfer money", "Change a setting"];

/**
 * The capability writ: what a key grants (read clauses) set against what it can
 * NEVER do (struck-through). The vault enforces this in code — a capability only
 * narrows the key's scopes, and the read session always rolls back — so this
 * panel is a true statement, not a promise.
 */
export function CapabilityStamps() {
  return (
    <div className="plate relative bg-card p-5">
      <div className="section-rule mb-4">
        <span className="dept-label whitespace-nowrap">What a key can do</span>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <Stamp variant="credit" still>
              Granted
            </Stamp>
            <span className="dept-label">read-only</span>
          </div>
          <ul className="space-y-1.5">
            {GRANTED.map((g) => (
              <li key={g} className="flex items-start gap-2 text-sm">
                <span className="mt-0.5 shrink-0 text-credit" aria-hidden>
                  ✓
                </span>
                <span>{g}</span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <div className="mb-2 flex items-center gap-2">
            <Stamp variant="debit" still>
              Never
            </Stamp>
            <span className="dept-label">no matter the key</span>
          </div>
          <ul className="space-y-1.5">
            {NEVER.map((n) => (
              <li
                key={n}
                className="flex items-start gap-2 text-sm text-muted-foreground line-through decoration-debit/60"
              >
                <span className="mt-0.5 shrink-0 text-debit no-underline" aria-hidden>
                  ✗
                </span>
                <span>{n}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p className="mt-4 border-t border-rule/60 pt-3 font-sans text-[12px] leading-relaxed text-muted-foreground">
        A capability can only <span className="text-foreground">narrow</span> a
        key's scopes — never widen them. The door an agent reaches opens read-only
        and rolls back every time, so a read cannot become a write.
      </p>
    </div>
  );
}
