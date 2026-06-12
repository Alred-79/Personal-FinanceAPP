import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Trash2, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { CATEGORIES } from "@/lib/colors";
import { formatCurrency } from "@/lib/format";

export interface Rule {
  id: number;
  name: string;
  enabled: boolean;
  conditions: Array<{ field: string; op: string; value: unknown }>;
  action_type: "notify" | "allocate" | "roundup" | "categorize";
  action_params: Record<string, unknown>;
  target_kind: string | null;
  target_id: number | null;
  priority: number;
}

interface RuleEditorProps {
  /** Pre-bound target: the editor only manages rules for this object. */
  targetKind: "goal";
  targetId: number;
  /** Called whenever the rule set changes (create/delete/toggle). */
  onChanged?: (rules: Rule[]) => void;
}

type NewAction = "roundup" | "allocate";

/**
 * The one reusable rule editor (condition + action + target), embedded where
 * the money lands — the Goal dialog's "Auto-fund" section — never its own
 * page. The target is pre-bound by the host surface.
 */
export function RuleEditor({ targetKind, targetId, onChanged }: RuleEditorProps) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  // New-rule form state.
  const [action, setAction] = useState<NewAction>("roundup");
  const [nearest, setNearest] = useState<"1" | "5">("1");
  const [allocMode, setAllocMode] = useState<"amount" | "pct">("amount");
  const [allocValue, setAllocValue] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("any");

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get("/rules/", {
        params: { target_kind: targetKind, target_id: targetId },
      });
      setRules(data);
      onChanged?.(data);
    } catch (error) {
      console.error("Error fetching rules:", error);
    } finally {
      setLoaded(true);
    }
  }, [targetKind, targetId, onChanged]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const describe = (rule: Rule): string => {
    const cond = rule.conditions.find((c) => c.field === "category");
    const scope = cond ? ` on ${String(cond.value)}` : "";
    if (rule.action_type === "roundup") {
      return `Rounds purchases${scope} up to the nearest $${rule.action_params.nearest ?? 1}`;
    }
    if (rule.action_type === "allocate") {
      if (rule.action_params.amount != null) {
        return `Moves ${formatCurrency(Number(rule.action_params.amount))} per purchase${scope}`;
      }
      return `Moves ${rule.action_params.pct}% of each purchase${scope}`;
    }
    return rule.name;
  };

  const handleAdd = async () => {
    setSaving(true);
    try {
      const conditions =
        categoryFilter !== "any"
          ? [{ field: "category", op: "eq", value: categoryFilter }]
          : [];
      const action_params =
        action === "roundup"
          ? { nearest }
          : allocMode === "amount"
          ? { amount: Number(allocValue) }
          : { pct: Number(allocValue) };
      const name =
        action === "roundup"
          ? `Round up to $${nearest}`
          : allocMode === "amount"
          ? `Move $${allocValue} per purchase`
          : `Move ${allocValue}% per purchase`;
      await api.post("/rules/", {
        name,
        action_type: action,
        action_params,
        conditions,
        target_kind: targetKind,
        target_id: targetId,
      });
      setAllocValue("");
      await refresh();
    } catch (error) {
      console.error("Error creating rule:", error);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (ruleId: number) => {
    try {
      await api.delete(`/rules/${ruleId}/`);
      await refresh();
    } catch (error) {
      console.error("Error deleting rule:", error);
    }
  };

  const addDisabled =
    saving || (action === "allocate" && (!allocValue || Number(allocValue) <= 0));

  return (
    <div className="grid gap-3 border-t border-rule pt-3">
      <p className="font-sans text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
        Auto-fund
      </p>

      {loaded && rules.length > 0 && (
        <ul className="grid gap-1">
          {rules.map((rule) => (
            <li
              key={rule.id}
              className="flex items-center justify-between gap-2 font-mono text-[11px] text-muted-foreground"
            >
              <span className="flex items-center gap-1.5 truncate">
                <RefreshCw size={11} className="shrink-0 text-credit" />
                {describe(rule)}
              </span>
              <button
                type="button"
                aria-label="Delete rule"
                className="text-muted-foreground transition-colors hover:text-debit"
                onClick={() => handleDelete(rule.id)}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid gap-1">
            <Label className="text-[11px]">When I spend…</Label>
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="h-8 w-[130px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Any category</SelectItem>
                {CATEGORIES.map((cat) => (
                  <SelectItem key={cat} value={cat}>
                    {cat}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1">
            <Label className="text-[11px]">then</Label>
            <Select value={action} onValueChange={(v) => setAction(v as NewAction)}>
              <SelectTrigger className="h-8 w-[110px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="roundup">Round up</SelectItem>
                <SelectItem value="allocate">Move</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {action === "roundup" ? (
            <div className="grid gap-1">
              <Label className="text-[11px]">to nearest</Label>
              <Select value={nearest} onValueChange={(v) => setNearest(v as "1" | "5")}>
                <SelectTrigger className="h-8 w-[72px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">$1</SelectItem>
                  <SelectItem value="5">$5</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : (
            <>
              <div className="grid gap-1">
                <Label className="text-[11px]">amount</Label>
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={allocValue}
                  onChange={(e) => setAllocValue(e.target.value)}
                  className="h-8 w-[84px] text-xs"
                />
              </div>
              <div className="grid gap-1">
                <Label className="text-[11px]">unit</Label>
                <Select
                  value={allocMode}
                  onValueChange={(v) => setAllocMode(v as "amount" | "pct")}
                >
                  <SelectTrigger className="h-8 w-[64px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="amount">$</SelectItem>
                    <SelectItem value="pct">%</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8"
            disabled={addDisabled}
            onClick={handleAdd}
          >
            Add
          </Button>
        </div>
        <p className="font-sans text-[10px] italic text-muted-foreground/70">
          Swept change earmarks into this goal and reduces Safe-to-Spend — no
          real transfer is made.
        </p>
      </div>
    </div>
  );
}
