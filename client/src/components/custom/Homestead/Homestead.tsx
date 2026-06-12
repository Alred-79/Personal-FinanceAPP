/**
 * <Homestead /> — the weekly reveal (v4 §6.5).
 *
 * The hero is the forward PROJECTION with one commit action (R14: reachable
 * default, one button). The accrual line renders ONLY when the server sent it
 * (it's omitted below $1.00 — never "you earned $0.04"). Hidden in off mode and
 * suppressed entirely under strain. All numbers are the engine's.
 */
import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { useFlags } from "@/store/gameMode";
import api from "@/lib/api";

interface Reveal {
  suppressed?: boolean;
  projection_date?: string;
  projection_cents?: number;
  action?: { kind: string; label: string; deep_link: string };
  accrual_cents?: number; // ABSENT when below the trivial-sum floor
}

function dollars(cents: number): string {
  return `$${Math.round(cents / 100).toLocaleString("en-US")}`;
}

export function Homestead() {
  const { gameLayer } = useFlags();
  const [reveal, setReveal] = useState<Reveal | null>(null);

  useEffect(() => {
    if (!gameLayer) return;
    api.get("/game/homestead/").then((r) => setReveal(r.data.reveal)).catch(() => {});
  }, [gameLayer]);

  if (!gameLayer || !reveal || reveal.suppressed) return null;

  return (
    <Card data-testid="homestead">
      <CardContent className="pt-6">
        <p className="dept-label text-[11px]">At this pace</p>
        <p data-testid="homestead-projection" className="font-display text-2xl font-semibold">
          {reveal.projection_cents != null ? dollars(reveal.projection_cents) : "—"}
          <span className="ml-2 text-sm text-muted-foreground">by {reveal.projection_date}</span>
        </p>

        {/* Accrual line — rendered ONLY when the server included the key. */}
        {reveal.accrual_cents != null ? (
          <p data-testid="homestead-accrual" className="mt-1 text-sm text-muted-foreground">
            {dollars(reveal.accrual_cents)} earned this period
          </p>
        ) : null}

        {reveal.action ? (
          <button
            data-testid="homestead-action"
            className="press mt-4 border border-gold/60 bg-gold/10 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-gold shadow-plate"
          >
            {reveal.action.label}
          </button>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default Homestead;
