import { useState } from "react";
import api from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Seal } from "@/components/engraving/Seal";

/**
 * The shared propose→confirm card (v6 doc 08): renders a human ``summary`` and
 * Approve / Decline. Approve POSTs the signed ``token`` to the existing confirm
 * endpoint (``api`` carries the 401→refresh→retry interceptor), and on success
 * presses an approved Seal. Reused by chat, Forecast, and Goals.
 */
export default function ConfirmCard({
  summary,
  token,
  onConfirmed,
  onDecline,
  approveLabel = "Approve",
  children,
}: {
  summary: string;
  token: string;
  /** Called with the confirm endpoint's ``result`` on success. */
  onConfirmed?: (result: unknown) => void;
  onDecline?: () => void;
  approveLabel?: string;
  /** Optional extra content (e.g. an inline diff) rendered above the actions. */
  children?: React.ReactNode;
}) {
  const [status, setStatus] = useState<"idle" | "working" | "approved" | "declined">(
    "idle"
  );
  const [error, setError] = useState<string | null>(null);

  const approve = async () => {
    setStatus("working");
    setError(null);
    try {
      const resp = await api.post("/assistant/actions/confirm/", { token });
      setStatus("approved");
      onConfirmed?.(resp.data?.result);
    } catch {
      setStatus("idle");
      setError("That didn't go through. Please try again.");
    }
  };

  const decline = () => {
    setStatus("declined");
    onDecline?.();
  };

  if (status === "declined") return null;

  return (
    <Card className="border-gold/40 animate-rise-in" data-testid="confirm-card">
      <CardContent className="space-y-3 p-5">
        <p className="dept-label text-gold">Confirm this change</p>
        <p className="font-sans text-sm text-foreground">{summary}</p>
        {children}
        {status === "approved" ? (
          <div className="flex items-center gap-3 pt-1">
            <Seal label="Approved · Recorded · Approved" size={48} tone="approved" pulse />
            <span className="font-sans text-sm text-credit">Done.</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 pt-1">
            <Button
              size="sm"
              onClick={approve}
              disabled={status === "working"}
              aria-label="Approve"
            >
              {status === "working" ? "Working…" : approveLabel}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={decline}
              aria-label="Decline"
            >
              Decline
            </Button>
          </div>
        )}
        {error && <p className="font-sans text-xs text-debit">{error}</p>}
      </CardContent>
    </Card>
  );
}
