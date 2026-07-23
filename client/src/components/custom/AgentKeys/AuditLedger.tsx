import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Stamp } from "@/components/engraving/Stamp";
import { CornerRosette } from "@/components/engraving/Guilloche";

interface AuditEntry {
  id: number;
  key_id: number | null;
  resource: string;
  decision: string; // "allow" | "deny:<reason>"
  latency_ms: number;
  params_hash: string;
  created_at: string | null;
}

const RESOURCE_LABEL: Record<string, string> = {
  tx_by_date: "Transactions by date",
  tx_by_category: "Transactions by category",
  tx_per_account: "Transactions per account",
  accounts: "Accounts",
  goals: "Goals",
  budgets: "Budgets",
  categories: "Categories",
  spend_summary: "Spend summary",
  context: "Context snapshot",
  ping: "Handshake",
  auth: "Authorization",
};

function rel(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso.replace(" ", "T")).getTime();
  if (Number.isNaN(then)) return "—";
  const s = (Date.now() - then) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86_400) return `${Math.round(s / 3600)}h ago`;
  return new Date(then).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/**
 * The Audit Ledger — every read (and resolvable denial) an agent made through
 * the vault, stamped allow/deny with its latency and a params FINGERPRINT (the
 * stored hash; raw inputs are never kept). The read side of the security story:
 * the user can verify exactly what was touched, and that nothing was written.
 */
export function AuditLedger() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    setLoaded(false);
    setFailed(false);
    void api
      .get<AuditEntry[]>("/mcp-keys/audit/")
      .then((r) => setRows(Array.isArray(r.data) ? r.data : []))
      .catch(() => setFailed(true))
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!loaded) {
    return <div className="plate min-h-48 animate-pulse bg-card" aria-label="Loading connection activity" />;
  }

  return (
    <div className="plate relative bg-card p-5">
      <div className="section-rule mb-4">
        <span className="dept-label whitespace-nowrap">The Audit Ledger</span>
      </div>

      {failed ? (
        <div className="grid place-items-center py-12 text-center" role="alert">
          <p className="font-display text-base">Could not load activity</p>
          <p className="mt-1 max-w-xs text-sm text-muted-foreground">
            Recorded authorized and scope-denied calls are temporarily unavailable.
          </p>
          <button
            type="button"
            onClick={load}
            className="press mt-4 min-h-11 border border-rule px-4 font-sans text-sm font-semibold"
          >
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="grid place-items-center py-12 text-center">
          <div className="text-rule-strong/40">
            <CornerRosette size={64} seed={19} />
          </div>
          <p className="mt-3 font-display text-base">No reads recorded</p>
          <p className="mt-1 max-w-xs text-sm text-muted-foreground">
            Recorded authorized and scope-denied calls will appear here with the
            resource, time, and decision.
          </p>
        </div>
      ) : (
        <ul>
          {rows.map((r) => {
            const allowed = r.decision === "allow";
            return (
              <li
                key={r.id}
                className="ledger-row flex items-center justify-between gap-4 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate font-sans text-sm font-semibold">
                    {RESOURCE_LABEL[r.resource] ?? r.resource}
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                    {r.params_hash && (
                      <span title="Inputs hashed — never stored raw">
                        #{r.params_hash}{" · "}
                      </span>
                    )}
                    {rel(r.created_at)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className="font-mono text-[10px] tabular-nums text-muted-foreground/70">
                    {Math.round(r.latency_ms)}ms
                  </span>
                  <Stamp variant={allowed ? "credit" : "debit"} still>
                    {allowed ? "Read" : "Denied"}
                  </Stamp>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-4 border-t border-rule/60 pt-3 text-center font-mono text-[10px] text-muted-foreground">
        Recorded inputs are hashed, never stored raw · authorized reads roll back
      </p>
    </div>
  );
}
