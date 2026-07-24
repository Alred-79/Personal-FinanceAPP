import { Link } from "react-router-dom";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { TiltCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Figure } from "@/components/engraving/Figure";
import { Stamp } from "@/components/engraving/Stamp";
import { useSafeToSpendTitle } from "@/components/custom/SafeToSpend/SafeToSpend";
import { SpendSettingsDialog } from "@/components/custom/SpendSettingsDialog/SpendSettingsDialog";
import { Button } from "@/components/ui/button";

function CardFrame({ children }: { children: React.ReactNode }) {
  return (
    <TiltCard>
      <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
        <CardTitle>Safe to Spend</CardTitle>
        <div className="flex items-center gap-2">
          <Button size="sm" className="min-h-11" asChild>
            <Link to="/forecast?tab=whatif">Test a decision</Link>
          </Button>
          <SpendSettingsDialog
            onWarningPositionChange={() => {}}
            onSavingsPercentChange={() => {}}
          />
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </TiltCard>
  );
}

export default function SpendCard() {
  const { safeToSpend: s2s, safeToSpendStatus, fetchSafeToSpend } = useStore();
  const status = safeToSpendStatus ?? (s2s ? "ready" : "idle");

  useSafeToSpendTitle(status === "ready" && s2s ? s2s.available : null, true);

  if (status === "idle" || status === "loading") {
    return (
      <CardFrame>
        <div className="space-y-3 py-8" role="status" aria-live="polite">
          <div className="h-12 w-48 animate-pulse bg-rule/40" />
          <p className="font-sans text-sm text-muted-foreground">
            Calculating from your accounts and scheduled cashflows…
          </p>
        </div>
      </CardFrame>
    );
  }

  if (status === "error" || !s2s) {
    return (
      <CardFrame>
        <div className="flex flex-col items-start gap-4 py-6" role="alert">
          <div className="flex items-center gap-2 text-debit">
            <AlertTriangle className="h-5 w-5" aria-hidden />
            <p className="font-display text-xl">This answer is unavailable</p>
          </div>
          <p className="max-w-2xl font-sans text-sm text-muted-foreground">
            No cached or estimated number is being substituted. Check the connection and try again.
          </p>
          <Button variant="outline" className="min-h-11" onClick={() => void fetchSafeToSpend()}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
            Try again
          </Button>
        </div>
      </CardFrame>
    );
  }

  const isNegative = s2s.available < 0 || s2s.is_negative === true;
  const isEmpty = s2s.state === "empty" || s2s.account_scope?.state === "empty";
  const isLimited = s2s.state === "limited" || s2s.account_scope?.state === "limited";
  const horizonLabel = new Date(`${s2s.horizon_end}T00:00:00`).toLocaleDateString(
    "en-US",
    { month: "short", day: "numeric" },
  );
  const accent = isNegative ? "hsl(var(--debit))" : "hsl(var(--credit))";
  const scope = s2s.account_scope;
  const equation = [
    ["Available cash", s2s.breakdown.current_balance, "+"],
    ["Bills before horizon", s2s.breakdown.upcoming_bills, "−"],
    ["Income before horizon", s2s.breakdown.projected_income, "+"],
    ["Already earmarked", s2s.breakdown.goal_earmarks, "−"],
    ["Goal contributions", s2s.breakdown.goal_contributions, "−"],
    ["Safety buffer", s2s.breakdown.buffer, "−"],
  ] as const;

  if (isEmpty) {
    return (
      <CardFrame>
        <div className="space-y-4 py-6">
          <p className="font-display text-2xl">Add a cash account to calculate this</p>
          <p className="max-w-2xl font-sans text-sm text-muted-foreground">
            Safe to Spend uses liquid cash, upcoming bills, expected income, goals, and your buffer. Credit availability and investments are not treated as spendable cash.
          </p>
          <Button className="min-h-11" asChild>
            <Link to="/accounts">Add an account</Link>
          </Button>
        </div>
      </CardFrame>
    );
  }

  return (
    <CardFrame>
      <div className="space-y-6">
        {isLimited && (
          <div className="flex items-start gap-2 border border-gold/35 bg-gold-soft/35 p-3 font-sans text-xs leading-5">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-gold" aria-hidden />
            <p>
              Limited account coverage. Review the excluded or unverified accounts below before relying on this figure.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="intaglio text-5xl leading-none md:text-6xl" style={{ color: accent }}>
              <AnimatedNumber value={s2s.available} format={(value) => formatCurrency(value)} />
            </p>
            <p className="mt-2 font-sans text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              {isNegative ? `Shortfall through ${horizonLabel}` : `Available through ${horizonLabel}`}
            </p>
          </div>
          <Stamp variant={isNegative ? "debit" : "credit"} still>
            {isNegative ? "Shortfall" : "Within plan"}
          </Stamp>
        </div>

        <div className="flex flex-wrap gap-px overflow-hidden border border-rule-strong/25 bg-rule-strong/15">
          {!isNegative && s2s.days_remaining > 0 && (
            <Figure label="Daily ceiling" value={formatCurrency(s2s.daily_plan)} />
          )}
          <Figure label="Days in horizon" value={String(s2s.days_remaining)} />
          <Figure label="Horizon rule" value={s2s.horizon_source.split("_").join(" ")} />
        </div>

        <section aria-labelledby="s2s-equation-title" className="border-t border-rule pt-4">
          <h3 id="s2s-equation-title" className="font-sans text-xs font-semibold uppercase tracking-[0.16em]">
            How this is calculated
          </h3>
          <div className="mt-3 grid gap-2 font-mono text-xs sm:grid-cols-2 lg:grid-cols-3">
            {equation.map(([label, amount, operator]) => (
              <div key={label} className="flex items-center justify-between gap-4 border-b border-rule/60 py-2">
                <span className="text-muted-foreground">{operator} {label}</span>
                <span>{formatCurrency(amount)}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between border-t-2 border-double border-rule-strong pt-3 font-mono text-sm font-semibold">
            <span>= Safe to Spend</span>
            <span style={{ color: accent }}>{formatCurrency(s2s.available)}</span>
          </div>
        </section>

        <section aria-labelledby="s2s-scope-title" className="border-t border-rule pt-4 font-sans text-xs">
          <h3 id="s2s-scope-title" className="font-semibold uppercase tracking-[0.16em]">
            Account coverage
          </h3>
          <p className="mt-2 text-muted-foreground">
            {scope
              ? `${scope.components.length} liquid account${scope.components.length === 1 ? "" : "s"} included; ${scope.exclusions.length} account${scope.exclusions.length === 1 ? "" : "s"} excluded.`
              : "Liquid cash accounts are included; credit availability and non-cash assets are excluded."}
          </p>
          {scope && scope.exclusions.length > 0 && (
            <ul className="mt-2 space-y-1 text-muted-foreground">
              {scope.exclusions.map((account) => (
                <li key={account.account_id}>
                  {account.name}: {account.reason.split("_").join(" ")}
                </li>
              ))}
            </ul>
          )}
        </section>

        {s2s.model_state === "historical_variation" && s2s.trough_band ? (
          <p className="border-t border-rule pt-3 font-mono text-[11px] text-muted-foreground">
            Modeled low-point range {formatCurrency(s2s.trough_band.low)}–{formatCurrency(s2s.trough_band.high)} · directional estimate
          </p>
        ) : (
          <p className="border-t border-rule pt-3 font-sans text-xs text-muted-foreground">
            Scheduled cashflows only. A risk range will appear after enough varied transaction history is available.
          </p>
        )}
      </div>
    </CardFrame>
  );
}
