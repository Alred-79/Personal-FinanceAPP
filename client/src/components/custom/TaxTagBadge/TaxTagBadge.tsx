import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * A small ledger chip marking a transaction's Schedule-C tax bucket — the
 * orthogonal tax axis, not the spend category. It states the bucket the user
 * applied (organization); it never asserts the expense is deductible.
 *
 * A "personal" tag (excluded from deductible totals) reads in muted ink so the
 * business/personal split is visible at a glance.
 */
export function TaxTagBadge({
  label,
  businessPersonal = "business",
  deductibleBps,
  className,
}: {
  /** Human bucket label, e.g. "Office expense (Sch C line 18)". */
  label: string;
  businessPersonal?: "business" | "personal";
  /** Optional deductible fraction in basis points (5000 = 50%). */
  deductibleBps?: number;
  className?: string;
}) {
  const isPersonal = businessPersonal === "personal";
  const pct =
    deductibleBps != null && deductibleBps < 10000
      ? ` · ${Math.round(deductibleBps / 100)}%`
      : "";
  return (
    <Badge
      variant={isPersonal ? "outline" : "secondary"}
      className={cn(
        "max-w-[16rem] truncate",
        isPersonal && "text-muted-foreground",
        className
      )}
      title={`${label}${isPersonal ? " (personal)" : ""} — organization only`}
    >
      ❧ {label}
      {pct}
    </Badge>
  );
}

export default TaxTagBadge;
