import { TiltCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Figure } from "@/components/engraving/Figure";
import { Stamp } from "@/components/engraving/Stamp";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { useSafeToSpendTitle } from "@/components/custom/SafeToSpend/SafeToSpend";
import { SpendSettingsDialog } from "@/components/custom/SpendSettingsDialog/SpendSettingsDialog";

/**
 * Safe-to-Spend — the Overview hero. A half-circle pressure gauge (the dial of
 * a cash register) sits beside the headline figure, the pace, a status stamp,
 * and the quiet breakdown that explains the number. The needle swings to the
 * spent fraction of this horizon's envelope; a fine tick marks the warning
 * threshold. The gear edits the rules behind the number. This card also drives
 * the browser tab title (it replaced the old flat SafeToSpend pane).
 */
export default function SpendCard() {
  const { spendOverTime, safeToSpend: s2s, budgetAllotment, warningPosition, savingsPercent, fixedPerMonth } =
    useStore();

  // Server number with a graceful fallback to the legacy client math while
  // the first fetch is in flight.
  const available = s2s ? Math.max(0, s2s.available) : Math.max(0, budgetAllotment - spendOverTime);
  const envelope = available + spendOverTime;
  const pct = envelope > 0 ? Math.min(100, (spendOverTime / envelope) * 100) : 0;
  const isOver = s2s ? s2s.available < 0 : spendOverTime > budgetAllotment;
  const isWarning = !isOver && pct >= warningPosition;
  const horizonLabel = s2s
    ? new Date(`${s2s.horizon_end}T00:00:00`).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : null;

  const accent = isOver
    ? "hsl(var(--debit))"
    : isWarning
    ? "hsl(var(--gold))"
    : "hsl(var(--credit))";

  // Status stamp wording avoids the substring "over" so the footer "% over" is
  // still the only /% over/ match the tests key on.
  const status = isOver
    ? { variant: "debit" as const, text: "Exceeded" }
    : isWarning
    ? { variant: "gold" as const, text: "Watch" }
    : { variant: "credit" as const, text: "On Track" };

  // Drive the tab title from the real (sign-preserving) figure, as the old flat
  // SafeToSpend hero did.
  useSafeToSpendTitle(s2s ? s2s.available : null, true);

  // Gauge geometry: a 180° arc from left (-180°) to right (0°).
  const R = 78;
  const cx = 100;
  const cy = 96;
  const needleAngle = Math.PI - (pct / 100) * Math.PI; // radians
  const nx = cx + R * 0.86 * Math.cos(needleAngle);
  const ny = cy - R * 0.86 * Math.sin(needleAngle);
  const warnAngle = Math.PI - (warningPosition / 100) * Math.PI;
  const wx1 = cx + R * Math.cos(warnAngle);
  const wy1 = cy - R * Math.sin(warnAngle);
  const wx2 = cx + (R + 9) * Math.cos(warnAngle);
  const wy2 = cy - (R + 9) * Math.sin(warnAngle);

  // The spent arc as a stroke-dash fraction of the semicircle.
  const arcLen = Math.PI * R;

  return (
    <TiltCard>
      <CardHeader className="flex flex-row items-center justify-between pb-1">
        <CardTitle>Safe to Spend</CardTitle>
        <SpendSettingsDialog
          onWarningPositionChange={() => {}}
          onSavingsPercentChange={() => {}}
        />
      </CardHeader>

      <CardContent>
        <Reveal className="space-y-5">
          {/* Headline row: the dial beside the figure, vertically centred */}
          <RevealItem className="grid items-center gap-x-8 gap-y-4 lg:grid-cols-[minmax(0,220px)_1fr]">
          <div className="mx-auto w-full max-w-[220px]">
            <svg viewBox="0 0 200 108" className="w-full">
              {/* tick marks every 10% */}
              {Array.from({ length: 11 }).map((_, i) => {
                const a = Math.PI - (i / 10) * Math.PI;
                const r1 = R + 2;
                const r2 = i % 5 === 0 ? R + 11 : R + 6;
                return (
                  <line
                    key={i}
                    x1={cx + r1 * Math.cos(a)}
                    y1={cy - r1 * Math.sin(a)}
                    x2={cx + r2 * Math.cos(a)}
                    y2={cy - r2 * Math.sin(a)}
                    stroke="hsl(var(--rule-strong))"
                    strokeWidth={i % 5 === 0 ? 1.1 : 0.6}
                    opacity={0.55}
                  />
                );
              })}
              {/* base arc */}
              <path
                d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`}
                fill="none"
                stroke="hsl(var(--rule))"
                strokeWidth="6"
              />
              {/* filled arc */}
              <path
                d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`}
                fill="none"
                stroke={accent}
                strokeWidth="6"
                strokeDasharray={arcLen}
                strokeDashoffset={arcLen * (1 - pct / 100)}
                style={{ transition: "stroke-dashoffset 900ms cubic-bezier(0.22,1,0.36,1)" }}
              />
              {/* warning tick */}
              {warningPosition > 0 && warningPosition < 100 && (
                <line
                  x1={wx1}
                  y1={wy1}
                  x2={wx2}
                  y2={wy2}
                  stroke="hsl(var(--gold))"
                  strokeWidth="1.6"
                />
              )}
              {/* needle */}
              <line
                x1={cx}
                y1={cy}
                x2={nx}
                y2={ny}
                stroke="hsl(var(--foreground))"
                strokeWidth="1.8"
                style={{ transition: "all 900ms cubic-bezier(0.22,1,0.36,1)" }}
              />
              <circle cx={cx} cy={cy} r="4" fill="hsl(var(--foreground))" />
              <circle cx={cx} cy={cy} r="7.5" fill="none" stroke="hsl(var(--rule-strong))" strokeWidth="1" />
            </svg>
          </div>

          {/* Right of the dial: the headline figure + status */}
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
            <div>
              <p
                className="intaglio text-5xl leading-none md:text-6xl"
                style={{ color: accent }}
              >
                <AnimatedNumber value={available} format={(n) => formatCurrency(n)} />
              </p>
              <p className="mt-2 font-sans text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
                {horizonLabel
                  ? `Safe to Spend · until ${horizonLabel}`
                  : "Safe to Spend"}
              </p>
              {/* F1: surface the calibrated band so the uncertainty behind the
                  number is visible. Calibrated → claim the coverage %; otherwise
                  a softer phrasing. Overdraft odds tint debit only when nonzero. */}
              {s2s?.trough_band && s2s.overdraft_probability != null && (
                <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                  {s2s.band_calibrated && s2s.coverage_level
                    ? `${Math.round(s2s.coverage_level * 100)}% chance you stay above `
                    : "low point likely above "}
                  <span className="text-foreground">
                    {formatCurrency(s2s.trough_band.low)}
                  </span>
                  <span className="mx-1.5 text-rule-strong">·</span>
                  <span
                    className={
                      s2s.overdraft_probability >= 0.1
                        ? "font-semibold text-debit"
                        : ""
                    }
                  >
                    overdraft {Math.round(s2s.overdraft_probability * 100)}%
                  </span>
                </p>
              )}
            </div>
            <Stamp variant={status.variant} still>
              {status.text}
            </Stamp>
            </div>
          </RevealItem>

          {/* Stats block: full width below the headline */}
          <RevealItem className="space-y-4">
            {/* Key stats as engraved plates */}
            <div className="flex flex-wrap gap-px overflow-hidden border border-rule-strong/25 bg-rule-strong/15">
              {s2s && s2s.days_remaining > 0 && (
                <Figure
                  label="Per day"
                  value={formatCurrency(s2s.daily_plan)}
                />
              )}
              {s2s && s2s.days_remaining > 0 && (
                <Figure
                  label="Days left"
                  value={String(s2s.days_remaining)}
                />
              )}
              <Figure
                label="Spent"
                value={`${pct.toFixed(0)}%${isOver ? " over" : ""}`}
                accent={isOver ? "debit" : undefined}
              />
            </div>

            <div className="flex items-center justify-between font-mono text-[11px] text-muted-foreground">
              <span>
                spent{" "}
                <span className="text-foreground">{formatCurrency(spendOverTime)}</span>
              </span>
              <span>of {formatCurrency(envelope)}</span>
            </div>

            {/* Why the number is what it is — the breakdown, one quiet line. */}
            {s2s && (s2s.breakdown.upcoming_bills > 0 || s2s.breakdown.goal_earmarks > 0 || s2s.breakdown.buffer > 0) && (
              <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-rule pt-3 font-sans text-[10px] text-muted-foreground/70">
                {s2s.breakdown.upcoming_bills > 0 && (
                  <span>Bills −{formatCurrency(s2s.breakdown.upcoming_bills)}</span>
                )}
                {s2s.breakdown.projected_income > 0 && (
                  <span className="text-credit/80">
                    Pay +{formatCurrency(s2s.breakdown.projected_income)}
                  </span>
                )}
                {s2s.breakdown.goal_earmarks > 0 && (
                  <span>Earmarked −{formatCurrency(s2s.breakdown.goal_earmarks)}</span>
                )}
                {s2s.breakdown.buffer > 0 && (
                  <span>Buffer −{formatCurrency(s2s.breakdown.buffer)}</span>
                )}
                {fixedPerMonth > 0 && <span>Fixed {formatCurrency(fixedPerMonth)}/mo</span>}
                {savingsPercent > 0 && <span className="ml-auto">{savingsPercent}% set aside</span>}
              </div>
            )}
          </RevealItem>
        </Reveal>
      </CardContent>
    </TiltCard>
  );
}
