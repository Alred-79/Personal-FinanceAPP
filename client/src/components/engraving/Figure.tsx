/**
 * A small engraved stat plate: an uppercase label over a ledger figure, tinted
 * by debit/credit accent. Extracted from Forecast.tsx so the Forecast page and
 * ScenarioCompare share one implementation (v6 doc 07).
 */
export function Figure({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "debit" | "credit";
}) {
  return (
    <div className="bg-card p-4">
      <p className="font-sans text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      <p
        className={`ledger-figures mt-1 text-base ${
          accent === "debit"
            ? "ink-debit"
            : accent === "credit"
            ? "ink-credit"
            : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
