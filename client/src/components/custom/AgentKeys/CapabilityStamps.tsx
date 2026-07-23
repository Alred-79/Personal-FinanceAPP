import { Stamp } from "@/components/engraving/Stamp";

const SCOPE_LABELS: Record<string, string> = {
  "read:accounts": "Accounts — names & balances",
  "read:transactions": "Transactions — posted debits & credits",
  "read:budgets": "Budgets — limits & pace",
  "read:goals": "Goals — targets & progress",
  "read:forecast": "Decisions — modeled cash outlook",
  "read:networth": "Net worth — totals & trend",
  "read:subscriptions": "Upcoming — recurring charges",
  "read:scenarios": "Saved decisions — uncommitted scenarios",
  "read:context": "Context — a read-only snapshot",
};

const NEVER = ["Write a transaction", "Move or transfer money", "Change a setting"];

/**
 * The capability writ: what a key grants (read clauses) set against what it can
 * NEVER do (struck-through). The vault enforces this in code — a capability only
 * narrows the key's scopes, and the read session always rolls back — so this
 * panel is a true statement, not a promise.
 */
export function CapabilityStamps({ grantedScopes }: { grantedScopes: string[] }) {
  const granted = grantedScopes.map((scope) => SCOPE_LABELS[scope] ?? scope);
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
            {granted.map((g) => (
              <li key={g} className="flex items-start gap-2 text-sm">
                <span className="mt-0.5 shrink-0 text-credit" aria-hidden>
                  ✓
                </span>
                <span>{g}</span>
              </li>
            ))}
            {granted.length === 0 && (
              <li className="text-sm text-muted-foreground">No permissions selected.</li>
            )}
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
        These are the permissions selected for the next key. A connected provider
        may copy data returned under them. Revocation prevents future access, but
        cannot delete copies the provider already received.
      </p>
    </div>
  );
}
