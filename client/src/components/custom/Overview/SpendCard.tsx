import { TiltCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { SpendSettingsDialog } from "@/components/custom/SpendSettingsDialog/SpendSettingsDialog";

/**
 * Safe-to-Spend, drawn as a half-circle pressure gauge — the dial of a cash
 * register. The number is the server's `safe_to_spend` (dynamic, anchored to
 * the next paycheck by default); the needle swings to the spent fraction of
 * this horizon's envelope; a fine tick marks the warning threshold. The gear
 * (SafeToSpend.Settings) edits the rules behind the number; the line under it
 * (SafeToSpend.Plan) is the "$X/day for N days" pace.
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

      <CardContent className="space-y-2">
        <div className="relative mx-auto w-full max-w-[230px]">
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

          <div className="mt-1 text-center">
            <p
              className="intaglio text-4xl leading-none"
              style={{ color: accent }}
            >
              <AnimatedNumber
                value={available}
                format={(n) => formatCurrency(n)}
              />
            </p>
            <p className="mt-1 font-sans text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
              {horizonLabel
                ? `Safe to Spend · until ${horizonLabel}`
                : "Safe to Spend"}
            </p>
            {/* SafeToSpend.Plan — Simplifi's spending plan for free */}
            {s2s && s2s.days_remaining > 0 && (
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                {formatCurrency(s2s.daily_plan)}/day for {s2s.days_remaining}{" "}
                day{s2s.days_remaining === 1 ? "" : "s"}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-rule pt-3 font-mono text-[11px] text-muted-foreground">
          <span>
            spent{" "}
            <span className="text-foreground">{formatCurrency(spendOverTime)}</span>
          </span>
          <span style={{ color: isOver || isWarning ? accent : undefined }}>
            {pct.toFixed(0)}%{isOver ? " over" : ""}
          </span>
          <span>of {formatCurrency(envelope)}</span>
        </div>

        {/* Why the number is what it is — the breakdown, one quiet line. */}
        {s2s && (s2s.breakdown.upcoming_bills > 0 || s2s.breakdown.goal_earmarks > 0 || s2s.breakdown.buffer > 0) && (
          <div className="flex flex-wrap justify-between gap-x-3 font-sans text-[10px] text-muted-foreground/70">
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
          </div>
        )}

        {(fixedPerMonth > 0 || savingsPercent > 0) && (
          <div className="flex justify-between font-sans text-[10px] text-muted-foreground/70">
            {fixedPerMonth > 0 && <span>Fixed {formatCurrency(fixedPerMonth)}/mo</span>}
            {savingsPercent > 0 && (
              <span className="ml-auto">{savingsPercent}% set aside</span>
            )}
          </div>
        )}
      </CardContent>
    </TiltCard>
  );
}
