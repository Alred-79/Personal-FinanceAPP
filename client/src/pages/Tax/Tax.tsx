import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { FilingStatus, MileageLog, TaxSummary } from "@/types";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/useToast";

/**
 * The Tax Organizer — a read-only-by-default desk that ORGANIZES, SUMMARIZES,
 * and ESTIMATES the user's own tagged numbers. It never gives tax advice: every
 * figure is a fact about the user's tags, the estimate is loudly labelled as an
 * estimate, and a standing notice points filing/eligibility questions to a
 * professional. Tax tags themselves are applied on the transaction (the Ledger);
 * this page is the year-level rollup plus the mileage log.
 */
export default function Tax() {
  const { toast } = useToast();
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState<number>(thisYear);
  const [summary, setSummary] = useState<TaxSummary | null>(null);
  const [mileage, setMileage] = useState<MileageLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [disabled, setDisabled] = useState(false);

  // estimate inputs — drive the two-lane quarterly engine.
  const [filingStatus, setFilingStatus] = useState<FilingStatus>("single");
  const [stateRatePct, setStateRatePct] = useState("");
  const [priorYearTax, setPriorYearTax] = useState("");
  const [paymentsMade, setPaymentsMade] = useState("");

  // mileage form
  const [tripDate, setTripDate] = useState(`${thisYear}-01-01`);
  const [miles, setMiles] = useState("");
  const [purpose, setPurpose] = useState("");
  const [saving, setSaving] = useState(false);

  const years = useMemo(
    () => [thisYear, thisYear - 1, thisYear - 2],
    [thisYear]
  );

  async function load(y: number) {
    setLoading(true);
    try {
      const params = new URLSearchParams({ filing_status: filingStatus });
      const sr = parseFloat(stateRatePct);
      if (!isNaN(sr) && sr > 0) params.set("state_rate_pct", String(sr));
      const py = parseFloat(priorYearTax);
      if (!isNaN(py) && py >= 0) params.set("prior_year_tax", String(py));
      const pm = parseFloat(paymentsMade);
      if (!isNaN(pm) && pm > 0) params.set("payments_made", String(pm));
      const [s, m] = await Promise.all([
        api.get(`/tax/summary/${y}/?${params.toString()}`),
        api.get(`/tax/mileage/?tax_year=${y}`),
      ]);
      setSummary(s.data);
      setMileage(m.data);
      setDisabled(false);
    } catch (e: unknown) {
      // 404 → the feature is off on this instance; anything else is a real error.
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        setDisabled(true);
      } else {
        toast({ title: "Could not load tax summary", variant: "destructive" });
      }
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(year);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, filingStatus, stateRatePct, priorYearTax, paymentsMade]);

  async function addMileage() {
    const m = parseFloat(miles);
    if (isNaN(m) || m <= 0) {
      toast({ title: "Enter a positive number of miles", variant: "destructive" });
      return;
    }
    setSaving(true);
    try {
      await api.post("/tax/mileage/", {
        trip_date: tripDate,
        miles: m,
        purpose: purpose || null,
      });
      setMiles("");
      setPurpose("");
      toast({ title: "Mileage logged" });
      await load(year);
    } catch {
      toast({ title: "Could not log mileage", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  }

  async function removeMileage(id: number) {
    try {
      await api.delete(`/tax/mileage/${id}/`);
      await load(year);
    } catch {
      toast({ title: "Could not remove", variant: "destructive" });
    }
  }

  if (disabled) {
    return (
      <div className="mx-auto max-w-3xl">
        <PageHeader
          title="Tax Organizer"
          reference="Form 1040-ORG"
          description="Organize your tagged income, deductions, and a rough estimate."
        />
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            Tax features are not enabled on this instance.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Tax Organizer"
        reference="Form 1040-ORG"
        description="Your own tagged numbers, organized. Not tax advice."
        actions={
          <Select
            value={String(year)}
            onValueChange={(v) => setYear(parseInt(v, 10))}
          >
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {years.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {/* Standing notice — this is organization, not advice. */}
      <p className="section-rule mb-6 text-center font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        Organization only · not tax advice · consult a professional
      </p>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-gold" />
        </div>
      ) : summary ? (
        <Reveal className="space-y-6">
          {/* Income by source (with provenance) */}
          <RevealItem>
          <Card raking>
            <CardHeader>
              <CardTitle>Income by source</CardTitle>
            </CardHeader>
            <CardContent>
              {summary.income_by_source.sources.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No tagged or documented income for {year}.
                </p>
              ) : (
                <ul className="divide-y divide-rule/50">
                  {summary.income_by_source.sources.map((s, i) => (
                    <li key={i} className="ledger-row flex items-center justify-between py-2">
                      <div className="min-w-0">
                        <p className="truncate text-[15px]">{s.issuer || "—"}</p>
                        <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                          {s.form_type || "ledger"} ·{" "}
                          {s.provenance === "from_document" ? "from document" : "from ledger"}
                        </p>
                      </div>
                      <span className="ledger-figures ink-credit tabular-nums">
                        {formatCurrency(s.income)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 flex items-center justify-between border-t border-rule-strong/40 pt-3 text-sm">
                <span className="dept-label">Total income</span>
                <span className="ledger-figures tabular-nums">
                  {formatCurrency(summary.income_by_source.total_income)}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>Documented withholding</span>
                <span className="ledger-figures tabular-nums">
                  {formatCurrency(summary.income_by_source.total_withholding)}
                </span>
              </div>
            </CardContent>
          </Card>
          </RevealItem>

          {/* Deductions by bucket */}
          <RevealItem>
          <Card raking>
            <CardHeader>
              <CardTitle>Deductions by bucket</CardTitle>
            </CardHeader>
            <CardContent>
              {summary.deductions_by_bucket.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No business-tagged expenses for {year}. Tag an expense from the
                  Ledger to see it here.
                </p>
              ) : (
                <ul className="divide-y divide-rule/50">
                  {summary.deductions_by_bucket.map((d) => (
                    <li key={d.bucket} className="ledger-row flex items-center justify-between py-2">
                      <div className="min-w-0">
                        <p className="truncate text-[15px]">{d.label}</p>
                        <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                          {d.irs_line} · {formatCurrency(d.total)} tagged
                        </p>
                      </div>
                      <span className="ledger-figures ink-debit tabular-nums">
                        {formatCurrency(d.deductible)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {summary.mileage.deduction > 0 && (
                <div className="mt-3 flex items-center justify-between border-t border-rule-strong/40 pt-3 text-sm">
                  <span>
                    Mileage ({summary.mileage.miles} mi @{" "}
                    {summary.mileage.rate_cents_per_mile}¢)
                  </span>
                  <span className="ledger-figures ink-debit tabular-nums">
                    {formatCurrency(summary.mileage.deduction)}
                  </span>
                </div>
              )}
            </CardContent>
          </Card>
          </RevealItem>

          {/* Estimated quarterly — LOUDLY an estimate */}
          <RevealItem>
          <Card raking className="border-gold/40">
            <CardHeader>
              <CardTitle>Estimated quarterly figure</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Inputs the estimate depends on */}
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1">
                  <label className="dept-label">Filing status</label>
                  <Select
                    value={filingStatus}
                    onValueChange={(v) => setFilingStatus(v as FilingStatus)}
                  >
                    <SelectTrigger className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="single">Single</SelectItem>
                      <SelectItem value="mfj">Married filing jointly</SelectItem>
                      <SelectItem value="mfs">Married filing separately</SelectItem>
                      <SelectItem value="hoh">Head of household</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="dept-label">State rate %</label>
                  <Input
                    type="number"
                    min={0}
                    max={20}
                    step="0.1"
                    placeholder="0"
                    value={stateRatePct}
                    onChange={(e) => setStateRatePct(e.target.value)}
                    className="w-24"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="dept-label">Last year's tax $</label>
                  <Input
                    type="number"
                    min={0}
                    step="1"
                    placeholder="optional"
                    value={priorYearTax}
                    onChange={(e) => setPriorYearTax(e.target.value)}
                    className="w-32"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="dept-label">Paid so far $</label>
                  <Input
                    type="number"
                    min={0}
                    step="1"
                    placeholder="0"
                    value={paymentsMade}
                    onChange={(e) => setPaymentsMade(e.target.value)}
                    className="w-28"
                  />
                </div>
              </div>

              <p className="intaglio text-3xl">
                <AnimatedNumber value={summary.estimated_quarterly.per_quarter} />
                <span className="ml-2 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  / quarter (estimate)
                </span>
              </p>

              {/* Two-lane breakdown so the number is auditable */}
              <ul className="space-y-1 border-t border-rule/40 pt-3 text-sm">
                {summary.estimated_quarterly.se_tax > 0 && (
                  <li className="flex justify-between">
                    <span className="text-muted-foreground">
                      Self-employment tax
                    </span>
                    <span className="ledger-figures tabular-nums">
                      {formatCurrency(summary.estimated_quarterly.se_tax)}
                    </span>
                  </li>
                )}
                <li className="flex justify-between">
                  <span className="text-muted-foreground">Federal income tax</span>
                  <span className="ledger-figures tabular-nums">
                    {formatCurrency(summary.estimated_quarterly.income_tax)}
                  </span>
                </li>
                {summary.estimated_quarterly.state_tax > 0 && (
                  <li className="flex justify-between">
                    <span className="text-muted-foreground">State tax (flat)</span>
                    <span className="ledger-figures tabular-nums">
                      {formatCurrency(summary.estimated_quarterly.state_tax)}
                    </span>
                  </li>
                )}
                <li className="flex justify-between border-t border-rule/40 pt-1">
                  <span>Estimated annual tax</span>
                  <span className="ledger-figures tabular-nums">
                    {formatCurrency(summary.estimated_quarterly.annual_estimate)}
                  </span>
                </li>
                {(summary.estimated_quarterly.total_withholding > 0 ||
                  summary.estimated_quarterly.payments_made > 0) && (
                  <li className="flex justify-between text-muted-foreground">
                    <span>Less withholding &amp; payments</span>
                    <span className="ledger-figures tabular-nums">
                      −
                      {formatCurrency(
                        summary.estimated_quarterly.total_withholding +
                          summary.estimated_quarterly.payments_made
                      )}
                    </span>
                  </li>
                )}
                <li className="flex justify-between font-medium">
                  <span>Still owed this year</span>
                  <span className="ledger-figures tabular-nums">
                    {formatCurrency(
                      summary.estimated_quarterly.remaining_estimate
                    )}
                  </span>
                </li>
              </ul>

              {/* Safe-harbor target, only when prior-year tax was entered */}
              {summary.estimated_quarterly.safe_harbor_per_quarter !== null && (
                <div className="border-l-2 border-gold/50 pl-3 text-sm">
                  <p className="dept-label">Safe-harbor target</p>
                  <p>
                    Paying{" "}
                    <span className="ledger-figures tabular-nums">
                      {formatCurrency(
                        summary.estimated_quarterly.safe_harbor_per_quarter
                      )}
                    </span>{" "}
                    / quarter likely avoids the underpayment penalty (the lesser of
                    90% of this year or 110% of last year's tax).
                  </p>
                </div>
              )}

              <p className="text-xs text-muted-foreground">
                {summary.estimated_quarterly.methodology}
              </p>
              <p className="border-l-2 border-gold/50 pl-3 text-xs font-medium text-foreground">
                {summary.estimated_quarterly.disclaimer}
              </p>
              <div className="flex flex-wrap gap-2 pt-1">
                {summary.estimated_quarterly.due_dates.map(([q, d]) => (
                  <span
                    key={q}
                    className="border border-rule-strong/40 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground"
                  >
                    {q} {d}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
          </RevealItem>

          {/* Mileage log */}
          <RevealItem>
          <Card raking>
            <CardHeader>
              <CardTitle>Business mileage log</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1">
                  <label className="dept-label">Date</label>
                  <Input
                    type="date"
                    value={tripDate}
                    onChange={(e) => setTripDate(e.target.value)}
                    className="w-40"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="dept-label">Miles</label>
                  <Input
                    type="number"
                    min={0}
                    step="0.1"
                    value={miles}
                    onChange={(e) => setMiles(e.target.value)}
                    className="w-28"
                  />
                </div>
                <div className="flex flex-1 flex-col gap-1">
                  <label className="dept-label">Purpose</label>
                  <Input
                    value={purpose}
                    onChange={(e) => setPurpose(e.target.value)}
                    placeholder="Client visit"
                  />
                </div>
                <Button onClick={addMileage} disabled={saving} className="press">
                  {saving ? "Logging…" : "Log trip"}
                </Button>
              </div>
              {mileage.length > 0 && (
                <ul className="divide-y divide-rule/50">
                  {mileage.map((m) => (
                    <li key={m.id} className="ledger-row flex items-center justify-between py-2 text-sm">
                      <span>
                        {m.trip_date} · {m.miles} mi
                        {m.purpose ? ` · ${m.purpose}` : ""}
                      </span>
                      <button
                        className="text-muted-foreground hover:text-debit"
                        onClick={() => removeMileage(m.id)}
                        aria-label="Remove mileage entry"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          </RevealItem>
        </Reveal>
      ) : null}
    </div>
  );
}
