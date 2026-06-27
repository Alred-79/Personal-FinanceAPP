import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/**
 * The freelancer wedge, foregrounded on the home surface for the self-employed user:
 * the three things they actually lose sleep over — the tax reserve, the typical
 * month under lumpy income, and the looming quarterly estimate.
 *
 * HONESTY (frontend re-eval): the app does NOT move or hold money. It ESTIMATES what
 * you'll owe, RECOMMENDS how much to hold back, and TRACKS a reserve Goal you fund
 * yourself — then hands you the move to make in your own bank. Copy here must reflect
 * that: no "we set aside / hold back / smoothed paycheck" language.
 *
 * Shows only when the user answered the self-employed fork AND the instance has the
 * freelancer model enabled (so the figures are real). Honest threshold states when
 * the model hasn't seen enough history yet; never a fabricated number.
 */
export function FreelancerLeadStrip() {
  const selfEmployed = useStore((s) => s.selfEmployed);
  const freelancerModeEnabled = useStore((s) => s.freelancerModeEnabled);
  const iv = useStore((s) => s.incomeVolatility);
  const ivLoaded = useStore((s) => s.incomeVolatilityLoaded);
  const fetchIncomeVolatility = useStore((s) => s.fetchIncomeVolatility);

  const active = selfEmployed === true && freelancerModeEnabled;

  useEffect(() => {
    if (active && !ivLoaded) fetchIncomeVolatility();
  }, [active, ivLoaded, fetchIncomeVolatility]);

  if (!active) return null;

  const quarterly = nextQuarterlyEstimate();

  return (
    <section
      className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      aria-label="Freelancer essentials"
    >
      {/* 1 — Tax reserve (a goal you fund; we estimate + track, you make the move) */}
      <LeadCard
        eyebrow="Tax reserve"
        to="/tax"
        cta="Open tax desk"
      >
        {iv?.tax_reserve ? (
          <>
            <Figure value={iv.tax_reserve.progress} />
            <p className="mt-1 text-[0.78rem] text-muted-foreground">
              you&rsquo;ve set aside, of your {formatCurrency(iv.tax_reserve.target)}{" "}
              target in {iv.tax_reserve.name}
            </p>
            <div className="mt-3" aria-hidden>
              <Progress
                value={pct(iv.tax_reserve.progress, iv.tax_reserve.target)}
              />
            </div>
          </>
        ) : (
          <Pending>
            We estimate what you&rsquo;ll owe and help you set it aside in a reserve
            you fund — we hand you the move; you make it in your bank.
          </Pending>
        )}
      </LeadCard>

      {/* 2 — Typical month (a measured average; we recommend a buffer, not a paycheck) */}
      <LeadCard
        eyebrow="Typical month"
        to="/income"
        cta="See income smoothing"
      >
        {iv && iv.sufficient_data ? (
          <>
            <Figure value={iv.mean_monthly} suffix=" / mo" />
            <p className="mt-1 text-[0.78rem] text-muted-foreground">
              your average under lumpy income · we recommend holding back{" "}
              {formatCurrency(iv.recommended_buffer)} in Safe-to-Spend for lean months
            </p>
          </>
        ) : (
          <Pending>
            <ThresholdLine
              current={iv?.months_observed ?? 0}
              required={3}
              unit="months of income"
            />
            A few months of history and we can recommend how much to hold back so a
            lean month still clears.
          </Pending>
        )}
      </LeadCard>

      {/* 3 — Quarterly estimate countdown (an estimate; the reserve is one you fund) */}
      <LeadCard
        eyebrow={`${quarterly.label} estimate`}
        to="/tax"
        cta="Review estimate"
      >
        <div className="ledger-figures text-[1.7rem] font-semibold text-foreground">
          due in {quarterly.daysUntil}{" "}
          <span className="text-[0.9rem] font-normal text-muted-foreground">
            {quarterly.daysUntil === 1 ? "day" : "days"}
          </span>
        </div>
        <p className="mt-1 text-[0.78rem] text-muted-foreground">
          {quarterly.dueLabel} · we&rsquo;ll estimate it and remind you to set the
          reserve aside before it lands.
        </p>
      </LeadCard>
    </section>
  );
}

function LeadCard({
  eyebrow,
  to,
  cta,
  children,
}: {
  eyebrow: string;
  to: string;
  cta: string;
  children: React.ReactNode;
}) {
  return (
    <article className="plate flex h-full flex-col bg-card p-5">
      <p className="dept-label text-gold">{eyebrow}</p>
      <div className="mt-2 flex-1">{children}</div>
      <Link
        to={to}
        className="press mt-4 inline-flex w-fit items-center gap-1 font-mono text-[11px] uppercase tracking-[0.14em] text-foreground hover:text-gold"
      >
        {cta}
        <span aria-hidden>→</span>
      </Link>
    </article>
  );
}

function Figure({ value, suffix }: { value: number; suffix?: string }) {
  return (
    <div className="ledger-figures text-[1.9rem] font-semibold text-foreground">
      {formatCurrency(value)}
      {suffix && (
        <span className="text-[0.9rem] font-normal text-muted-foreground">
          {suffix}
        </span>
      )}
    </div>
  );
}

function Pending({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[0.85rem] leading-relaxed text-muted-foreground">
      {children}
    </p>
  );
}

/** A compact honest threshold line — "1 / 3 months of income · 2 to go". */
function ThresholdLine({
  current,
  required,
  unit,
}: {
  current: number;
  required: number;
  unit: string;
}) {
  const clamped = Math.max(0, Math.min(current, required));
  return (
    <span className="mb-1.5 flex items-baseline gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
      <span className="text-foreground">{clamped}</span> / {required} {unit}
      {clamped < required && (
        <span className={cn("text-muted-foreground/70")}>
          · {required - clamped} to go
        </span>
      )}
    </span>
  );
}

function pct(progress: number, target: number): number {
  if (target <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((progress / target) * 100)));
}

/**
 * The next IRS estimated-tax due date, computed client-side (no backend). Standard
 * quarterly deadlines: Apr 15, Jun 15, Sep 15, Jan 15 (following year). Approximate
 * weekend/holiday shifts are not material to a countdown headline.
 */
function nextQuarterlyEstimate(): {
  label: string;
  dueLabel: string;
  daysUntil: number;
} {
  const now = new Date();
  const y = now.getFullYear();
  const candidates = [
    { label: "Q1", m: 3, d: 15, yr: y },
    { label: "Q2", m: 5, d: 15, yr: y },
    { label: "Q3", m: 8, d: 15, yr: y },
    { label: "Q4", m: 0, d: 15, yr: y + 1 },
  ];
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  for (const c of candidates) {
    const due = new Date(c.yr, c.m, c.d);
    if (due >= today) {
      const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
      return {
        label: c.label,
        dueLabel: due.toLocaleDateString("en-US", {
          month: "long",
          day: "numeric",
        }),
        daysUntil: days,
      };
    }
  }
  // Past Jan 15 of next year shouldn't happen (Q4 is always ahead), but be safe.
  const due = new Date(y + 1, 3, 15);
  return {
    label: "Q1",
    dueLabel: due.toLocaleDateString("en-US", { month: "long", day: "numeric" }),
    daysUntil: Math.round((due.getTime() - today.getTime()) / 86_400_000),
  };
}
