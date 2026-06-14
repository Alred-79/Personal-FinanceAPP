import { useState } from "react";
import { CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { useStore } from "@/store/store";
import { ImportSession, ImportRow } from "@/types";
import { formatCurrency } from "@/lib/format";
import { statusLabel } from "@/lib/imports";
import { CATEGORIES } from "@/lib/colors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionRule } from "@/components/engraving/SectionRule";
import ConfirmCard from "@/components/custom/ConfirmCard/ConfirmCard";

interface ReconciliationReviewProps {
  session: ImportSession;
  /** Replace the session in the parent after an edit re-reconciles it. */
  onSessionChange: (session: ImportSession) => void;
  /** Called once the import is committed (e.g. to refetch and reset the page). */
  onCommitted: () => void;
  /** Called when the user discards the session. */
  onDiscarded: () => void;
}

/**
 * The review surface for a parsed import session. The headline is the balance
 * check: green when the statement reconciles, amber when it doesn't — with the
 * exact gap and the offending rows flagged. Each row is editable (the user can
 * fix a misread amount/date/category or exclude a row), and edits re-reconcile
 * live. Commit goes through the shared propose→confirm `ConfirmCard`.
 */
export default function ReconciliationReview({
  session,
  onSessionChange,
  onCommitted,
  onDiscarded,
}: ReconciliationReviewProps) {
  const patchImportRow = useStore((s) => s.patchImportRow);
  const discardImportSession = useStore((s) => s.discardImportSession);

  const [proposal, setProposal] = useState<{ summary: string; token: string } | null>(
    null
  );
  const [proposing, setProposing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bc = session.balance_check;
  const includedCount = session.rows.filter((r) => r.included).length;

  const patch = async (
    rowId: number,
    p: Partial<Pick<ImportRow, "title" | "amount" | "date" | "category" | "included">>
  ) => {
    try {
      const next = await patchImportRow(session.id, rowId, p);
      onSessionChange(next);
    } catch {
      setError("That edit didn't save. Please try again.");
    }
  };

  const propose = async () => {
    setProposing(true);
    setError(null);
    try {
      const resp = await api.post("/assistant/actions/propose/", {
        action: "commit_import_session",
        params: { session_id: session.id },
      });
      setProposal({ summary: resp.data.summary, token: resp.data.token });
    } catch {
      setError("Could not prepare the import. Please try again.");
    } finally {
      setProposing(false);
    }
  };

  const discard = async () => {
    try {
      await discardImportSession(session.id);
      onDiscarded();
    } catch {
      setError("Could not discard the session.");
    }
  };

  return (
    <div className="space-y-6">
      {/* ── Balance banner ─────────────────────────────────────────────── */}
      <div
        className={`plate flex flex-col gap-2 p-5 sm:flex-row sm:items-center sm:justify-between ${
          bc.reconciled ? "border-credit/50" : "border-gold/60"
        }`}
        data-testid="balance-banner"
      >
        <div className="flex items-center gap-3">
          {bc.reconciled ? (
            <CheckCircle2 className="h-6 w-6 text-credit" />
          ) : (
            <AlertTriangle className="h-6 w-6 text-gold" />
          )}
          <div>
            <p className="dept-label">
              {bc.reconciled ? "Reconciled" : "Needs a look"}
            </p>
            <p className="font-sans text-sm text-foreground">
              {bc.reconciled
                ? bc.opening != null && bc.closing != null
                  ? `Opening ${formatCurrency(bc.opening)} + ${includedCount} txns = closing ${formatCurrency(bc.closing)}.`
                  : `${includedCount} transactions ready to import.`
                : bc.discrepancy != null
                  ? `Off by ${formatCurrency(Math.abs(bc.discrepancy))}${bc.exception_count ? ` — ${bc.exception_count} row${bc.exception_count > 1 ? "s" : ""} need review.` : "."}`
                  : `${bc.exception_count} row${bc.exception_count === 1 ? "" : "s"} need review.`}
            </p>
          </div>
        </div>
        {session.detected_kind && (
          <Badge variant="outline">{session.detected_kind}</Badge>
        )}
      </div>

      {/* ── Row table ──────────────────────────────────────────────────── */}
      <div className="plate overflow-hidden">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule-strong/40 text-left">
              <th className="w-10 px-3 py-2"></th>
              <th className="px-3 py-2 font-sans font-medium">Description</th>
              <th className="px-3 py-2 font-sans font-medium">Date</th>
              <th className="px-3 py-2 font-sans font-medium">Category</th>
              <th className="px-3 py-2 text-right font-sans font-medium">Amount</th>
              <th className="px-3 py-2 font-sans font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {session.rows.map((row) => {
              const s = statusLabel(row.status);
              return (
                <tr
                  key={row.id}
                  className={`ledger-row border-b border-rule/60 ${
                    row.included ? "" : "opacity-50"
                  }`}
                >
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={row.included}
                      onChange={(e) => patch(row.id, { included: e.target.checked })}
                      aria-label={`Include ${row.title}`}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      value={row.title}
                      onChange={(e) => patch(row.id, { title: e.target.value })}
                      className="h-8 border-transparent bg-transparent px-1 shadow-none focus:border-rule-strong/50"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      type="date"
                      value={row.date}
                      onChange={(e) => patch(row.id, { date: e.target.value })}
                      className="h-8 w-36 border-transparent bg-transparent px-1 shadow-none focus:border-rule-strong/50"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Select
                      value={CATEGORIES.includes(row.category as never) ? row.category : "Other"}
                      onValueChange={(v) => patch(row.id, { category: v })}
                    >
                      <SelectTrigger className="h-8 w-36 border-transparent bg-transparent px-1 shadow-none">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {CATEGORIES.map((c) => (
                          <SelectItem key={c} value={c}>
                            {c}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td
                    className={`ledger-figures px-3 py-2 text-right ${
                      row.amount < 0 ? "ink-debit" : "ink-credit"
                    }`}
                  >
                    {formatCurrency(row.amount)}
                  </td>
                  <td className="px-3 py-2">
                    <Badge
                      variant={
                        s.tone === "ok"
                          ? "secondary"
                          : s.tone === "dup"
                            ? "outline"
                            : "destructive"
                      }
                    >
                      {s.label}
                    </Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <SectionRule>Confirm</SectionRule>

      {/* ── Commit / discard ───────────────────────────────────────────── */}
      {proposal ? (
        <ConfirmCard
          summary={proposal.summary}
          token={proposal.token}
          approveLabel={`Import ${includedCount} transaction${includedCount === 1 ? "" : "s"}`}
          onConfirmed={onCommitted}
          onDecline={() => setProposal(null)}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={propose} disabled={proposing || includedCount === 0}>
            {proposing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Preparing…
              </>
            ) : (
              `Import ${includedCount} transaction${includedCount === 1 ? "" : "s"}`
            )}
          </Button>
          <Button variant="outline" onClick={discard}>
            Discard
          </Button>
          {!bc.reconciled && (
            <span className="font-sans text-xs text-muted-foreground">
              You can import anyway — excluded and flagged rows are skipped.
            </span>
          )}
        </div>
      )}
      {error && <p className="font-sans text-xs text-debit">{error}</p>}
    </div>
  );
}
