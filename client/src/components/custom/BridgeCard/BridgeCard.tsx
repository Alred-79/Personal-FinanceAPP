import { useState } from "react";
import api from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Seal } from "@/components/engraving/Seal";
import { formatCurrency } from "@/lib/format";
import { ArrowRight, Copy, ExternalLink } from "lucide-react";
import type { AssistantBridge } from "@/types";
import { BridgeProgress } from "./BridgeProgress";
import { HumanInLoopBadge } from "@/components/custom/Trust/HumanInLoopBadge";

/**
 * The Assisted Action Bridge card (Pillar 2C). The agent has deduced the EXACT
 * real-world action — transfer $X from A→B, pay $Y to the IRS — and removed all
 * friction. The human pulls the irreversible trigger in their real bank; the app
 * verifies it on the next sync.
 *
 * Two stages:
 *  1. Record — "Set this up" POSTs the confirm token, which CREATES the Bridge
 *     object (no money moves). On success we get its id.
 *  2. Execute — the one-tap affordance ([Do it in my bank →] deep link / copy the
 *     prefilled instruction) + [I did it ✓] (provisional; the sync verifies it).
 */
export default function BridgeCard({
  bridge,
  onDismiss,
}: {
  bridge: AssistantBridge;
  onDismiss: () => void;
}) {
  const b = bridge.bridge;
  const [stage, setStage] = useState<"propose" | "recorded" | "done">("propose");
  const [actionId, setActionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);

  const kindLabel = b.kind.replace(/_/g, " ");
  const instruction =
    b.how?.instruction ||
    `At your bank: ${kindLabel} of ${formatCurrency(b.amount)}` +
      (b.source_ref ? ` from ${b.source_ref}` : "") +
      (b.dest_ref ? ` to ${b.dest_ref}` : "") +
      ".";

  const record = async () => {
    setWorking(true);
    setError(null);
    try {
      const resp = await api.post("/assistant/actions/confirm/", {
        token: bridge.confirm_token,
      });
      const id = resp.data?.result?.assisted_action_id ?? null;
      setActionId(id);
      setStage("recorded");
    } catch {
      setError("That didn't go through. Please try again.");
    } finally {
      setWorking(false);
    }
  };

  const transition = async (op: "acknowledge" | "done") => {
    if (actionId == null) return;
    try {
      await api.post(`/assisted-actions/${actionId}/${op}/`);
    } catch {
      /* best-effort — the user's real action is what matters */
    }
  };

  const openBank = () => {
    transition("acknowledge");
    if (b.how?.deep_link) window.open(b.how.deep_link, "_blank", "noopener");
  };

  const copyInstruction = async () => {
    try {
      await navigator.clipboard.writeText(instruction);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — the instruction is visible to read anyway */
    }
  };

  const markDone = async () => {
    await transition("done");
    setStage("done");
  };

  return (
    <div className="my-2" data-testid="bridge-card">
      <Card className="border-gold/40 animate-rise-in">
        <CardContent className="space-y-3 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="dept-label text-gold uppercase tracking-[0.18em]">
              {kindLabel}
            </p>
            {/* the honest lifecycle, visible: Drafted → You do it → Verified */}
            <BridgeProgress stage={stage} />
          </div>

          {/* amount + source→dest */}
          <div className="flex items-center justify-between gap-3">
            <span className="ledger-figures text-xl text-foreground">
              {formatCurrency(b.amount)}
            </span>
            {(b.source_ref || b.dest_ref) && (
              <span className="flex items-center gap-2 font-sans text-xs text-muted-foreground">
                <span>{b.source_ref ?? "—"}</span>
                <ArrowRight className="h-3 w-3" />
                <span>{b.dest_ref ?? "—"}</span>
              </span>
            )}
          </div>

          {/* the "why" — factual, screened server-side */}
          <p className="font-sans text-sm text-foreground">{b.rationale}</p>

          {/* the prefilled instruction (always available — degrade gracefully) */}
          <div className="rounded-none border border-rule/60 bg-card/60 p-3">
            <p className="font-sans text-sm text-foreground">{instruction}</p>
            <button
              type="button"
              onClick={copyInstruction}
              className="mt-2 inline-flex items-center gap-1 font-sans text-xs text-gold hover:underline"
            >
              <Copy className="h-3 w-3" />
              {copied ? "Copied" : "Copy details"}
            </button>
          </div>

          {stage === "done" ? (
            <div className="flex items-center gap-3 pt-1">
              <Seal label="Marked done · Verifying on sync" size={48} tone="approved" pulse />
              <span className="font-sans text-sm text-credit">
                I'll confirm it on your next bank sync.
              </span>
            </div>
          ) : stage === "recorded" ? (
            <div className="space-y-2 pt-1">
              <p className="font-sans text-sm text-foreground">
                Here&rsquo;s the exact move. Tap to do it in your bank — I&rsquo;ll
                confirm it went through on your next sync.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={openBank} aria-label="Do it in my bank">
                  {b.how?.deep_link ? (
                    <>
                      <ExternalLink className="mr-1 h-3.5 w-3.5" />
                      Do it in my bank
                    </>
                  ) : (
                    "Do it in my bank"
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={markDone}
                  aria-label="I did it"
                >
                  I did it ✓
                </Button>
                <Button size="sm" variant="ghost" onClick={onDismiss} aria-label="Dismiss">
                  Dismiss
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-2 pt-1">
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  onClick={record}
                  disabled={working}
                  aria-label="Set this up"
                >
                  {working ? "Working…" : "Set this up"}
                </Button>
                <Button size="sm" variant="outline" onClick={onDismiss} aria-label="Decline">
                  Not now
                </Button>
              </div>
              <HumanInLoopBadge />
            </div>
          )}
          {error && <p className="font-sans text-xs text-debit">{error}</p>}
        </CardContent>
      </Card>
    </div>
  );
}
