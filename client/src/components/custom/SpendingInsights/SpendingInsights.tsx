import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronUp } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency, categoryColor } from "@/lib/format";

interface AnalyticsResponse {
  bucket: string;
  cells: Array<{
    bucket: string;
    category: string;
    total: number;
    count: number;
  }>;
  totals_by_category: Record<string, number>;
  totals_by_bucket: Record<string, number>;
  grand_total: number;
}

/**
 * Spending insights (v2 analytics): totals by category × time bucket, the
 * "slice it like a database" view — folded into the Ledger page as a
 * collapsible section rather than a separate analytics page.
 */
export default function SpendingInsights() {
  const [open, setOpen] = useState(false);
  const [bucket, setBucket] = useState<"month" | "week">("month");
  const [data, setData] = useState<AnalyticsResponse | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .get("/analytics/spending/", { params: { bucket } })
      .then(({ data }) => {
        if (!cancelled) setData(data);
      })
      .catch((error) => console.error("Error fetching analytics:", error));
    return () => {
      cancelled = true;
    };
  }, [open, bucket]);

  const buckets = data ? Object.keys(data.totals_by_bucket).sort().slice(-6) : [];
  const categories = data
    ? Object.keys(data.totals_by_category).slice(0, 8)
    : [];
  const cellMap: Record<string, number> = {};
  data?.cells.forEach((c) => {
    cellMap[`${c.bucket}|${c.category}`] = c.total;
  });

  return (
    <Card className="mb-6">
      <CardHeader
        className="cursor-pointer flex-row items-center justify-between space-y-0 py-3"
        onClick={() => setOpen((o) => !o)}
      >
        <CardTitle className="text-sm">Spending Insights</CardTitle>
        <span className="text-muted-foreground">
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </span>
      </CardHeader>
      {open && (
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <Select value={bucket} onValueChange={(v) => setBucket(v as "month" | "week")}>
              <SelectTrigger className="h-8 w-[120px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="month">By month</SelectItem>
                <SelectItem value="week">By week</SelectItem>
              </SelectContent>
            </Select>
            {data && (
              <p className="font-mono text-[11px] text-muted-foreground">
                Total {formatCurrency(data.grand_total)}
              </p>
            )}
          </div>

          {data && buckets.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full font-mono text-[11px]">
                <thead>
                  <tr className="border-b border-rule text-muted-foreground">
                    <th className="py-1 pr-2 text-left font-normal">Category</th>
                    {buckets.map((b) => (
                      <th key={b} className="px-2 py-1 text-right font-normal">
                        {b}
                      </th>
                    ))}
                    <th className="py-1 pl-2 text-right font-normal">Σ</th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map((cat) => (
                    <tr key={cat} className="border-b border-rule/40">
                      <td className="py-1 pr-2">
                        <span className="flex items-center gap-1.5">
                          <span
                            className="inline-block h-2 w-2 shrink-0"
                            style={{ backgroundColor: categoryColor(cat) }}
                          />
                          {cat}
                        </span>
                      </td>
                      {buckets.map((b) => {
                        const v = cellMap[`${b}|${cat}`];
                        return (
                          <td key={b} className="px-2 py-1 text-right text-muted-foreground">
                            {v ? formatCurrency(v) : "·"}
                          </td>
                        );
                      })}
                      <td className="py-1 pl-2 text-right text-foreground">
                        {formatCurrency(data.totals_by_category[cat])}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-4 text-center font-sans text-sm italic text-muted-foreground">
              {data ? "Nothing posted yet." : "Loading…"}
            </p>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-full font-sans text-[10px] text-muted-foreground"
            onClick={() => setOpen(false)}
          >
            Collapse
          </Button>
        </CardContent>
      )}
    </Card>
  );
}
