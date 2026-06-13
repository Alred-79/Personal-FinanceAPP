import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { CATEGORIES } from "@/lib/colors";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CornerRosette } from "@/components/engraving/Guilloche";

/* ──────────────────────────────────────────────────────────────────────────
 * STANDING ORDERS
 *
 * The register of automation rules that fire on every posted transaction. This
 * is the central place to SEE all rules and CREATE the two kinds that aren't
 * bound to a goal: re-filing (categorize) and watch-notices (notify). The
 * goal-funding rules (round-up / move) are issued where the money lands — the
 * Goal dialog — so they appear here as read-only entries, never duplicated.
 * ────────────────────────────────────────────────────────────────────────── */

interface Rule {
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

const KIND_META: Record<Rule["action_type"], { glyph: string; label: string }> = {
  categorize: { glyph: "❧", label: "Re-file" },
  notify: { glyph: "❀", label: "Notice" },
  allocate: { glyph: "✦", label: "Auto-fund" },
  roundup: { glyph: "⊚", label: "Round-up" },
};

function conditionCategory(rule: Rule): string | null {
  const c = rule.conditions.find((x) => x.field === "category");
  return c ? String(c.value) : null;
}

function describe(rule: Rule): string {
  const cat = conditionCategory(rule);
  const on = cat ? ` on ${cat}` : " on any purchase";
  switch (rule.action_type) {
    case "categorize":
      return `Re-files${cat ? ` ${cat}` : " matching purchases"} as ${rule.action_params.category}`;
    case "notify":
      return `Notifies you${on}${rule.action_params.message ? ` — “${rule.action_params.message}”` : ""}`;
    case "roundup":
      return `Rounds up${on} to $${rule.action_params.nearest ?? 1}`;
    case "allocate":
      return rule.action_params.amount != null
        ? `Moves $${rule.action_params.amount} per purchase${on}`
        : `Moves ${rule.action_params.pct}% per purchase${on}`;
  }
}

export function StandingOrders() {
  const { toast } = useToast();
  const [rules, setRules] = useState<Rule[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<Rule[]>("/rules/");
      setRules(Array.isArray(data) ? data : []);
    } catch {
      toast({ title: "Could not load rules", variant: "destructive" });
    } finally {
      setLoaded(true);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const toggle = async (rule: Rule) => {
    try {
      await api.put(`/rules/${rule.id}/`, { ...rule, enabled: !rule.enabled });
      refresh();
    } catch {
      toast({ title: "Could not update rule", variant: "destructive" });
    }
  };

  const remove = async (rule: Rule) => {
    if (!confirm(`Strike "${rule.name}" from the register?`)) return;
    try {
      await api.delete(`/rules/${rule.id}/`);
      toast({ title: "Order struck" });
      refresh();
    } catch {
      toast({ title: "Could not delete rule", variant: "destructive" });
    }
  };

  const enabledCount = useMemo(() => rules.filter((r) => r.enabled).length, [rules]);

  return (
    <section className="relative">
      <header className="plate relative overflow-hidden bg-card px-6 py-5">
        <div className="pointer-events-none absolute -right-5 -top-6 text-gold/15">
          <CornerRosette size={108} seed={88} />
        </div>
        <div className="relative flex items-center justify-between gap-4">
          <div>
            <p className="dept-label">Office of Automated Bookkeeping</p>
            <h3 className="mt-1 font-display text-2xl leading-tight tracking-tight">
              Standing Orders
            </h3>
            <p className="mt-1 max-w-md text-sm text-muted-foreground">
              Instructions that execute on every posted transaction — re-filing a
              category, or raising a notice when you spend.
            </p>
          </div>
          <div className="hidden shrink-0 text-right sm:block">
            <p className="intaglio text-4xl leading-none ledger-figures">{enabledCount}</p>
            <p className="dept-label mt-1">active</p>
          </div>
        </div>
      </header>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <DraftOrder onCreated={refresh} />
        <OrderRegister
          rules={rules}
          loaded={loaded}
          onToggle={toggle}
          onRemove={remove}
        />
      </div>
    </section>
  );
}

/* ── Draft a new standing order (categorize or notify) ────────────────────── */
function DraftOrder({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast();
  const [kind, setKind] = useState<"categorize" | "notify">("categorize");
  const [whenCat, setWhenCat] = useState<string>(CATEGORIES[0] ?? "Other");
  const [toCat, setToCat] = useState<string>(CATEGORIES[1] ?? "Other");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (kind === "categorize" && whenCat === toCat) {
      toast({ title: "Pick two different categories", variant: "destructive" });
      return;
    }
    setSaving(true);
    try {
      const conditions = [{ field: "category", op: "eq", value: whenCat }];
      const body =
        kind === "categorize"
          ? {
              name: `Re-file ${whenCat} → ${toCat}`,
              action_type: "categorize",
              action_params: { category: toCat },
              conditions,
            }
          : {
              name: `Notice on ${whenCat}`,
              action_type: "notify",
              action_params: message.trim() ? { message: message.trim() } : {},
              conditions,
            };
      await api.post("/rules/", body);
      setMessage("");
      toast({ title: "Order entered" });
      onCreated();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not enter the order.";
      toast({ title: "Refused", description: detail, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="plate relative bg-card p-5">
      <div className="section-rule mb-4">
        <span className="dept-label whitespace-nowrap">Draft an Order</span>
      </div>

      {/* kind toggle */}
      <div className="grid grid-cols-2 gap-1">
        {(["categorize", "notify"] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            className={cn(
              "press border py-2 font-sans text-xs font-semibold uppercase tracking-[0.14em] transition-colors",
              kind === k
                ? "border-rule-strong bg-primary text-primary-foreground"
                : "border-rule text-muted-foreground hover:border-rule-strong hover:text-foreground"
            )}
          >
            <span className="mr-1.5 text-gold">{KIND_META[k].glyph}</span>
            {KIND_META[k].label}
          </button>
        ))}
      </div>

      {/* condition */}
      <div className="mt-5">
        <span className="dept-label">When a purchase is filed under</span>
        <Select value={whenCat} onValueChange={setWhenCat}>
          <SelectTrigger className="mt-1.5">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CATEGORIES.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* action */}
      {kind === "categorize" ? (
        <div className="mt-4">
          <span className="dept-label">Re-file it as</span>
          <Select value={toCat} onValueChange={setToCat}>
            <SelectTrigger className="mt-1.5">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : (
        <div className="mt-4">
          <label className="dept-label" htmlFor="notice-msg">
            Notice to raise <span className="normal-case text-muted-foreground/60">(optional)</span>
          </label>
          <input
            id="notice-msg"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={`Spent in ${whenCat}`}
            maxLength={120}
            className={cn(
              "mt-1.5 w-full border-b border-rule bg-transparent px-0 py-1.5 font-sans text-sm",
              "placeholder:text-muted-foreground/50 focus:border-gold focus:outline-none"
            )}
          />
        </div>
      )}

      <button
        type="submit"
        disabled={saving}
        className={cn(
          "press mt-6 flex w-full items-center justify-center gap-2 border border-rule-strong bg-primary py-2.5",
          "font-sans text-sm font-semibold uppercase tracking-[0.18em] text-primary-foreground disabled:opacity-60"
        )}
      >
        {saving ? "Entering…" : "Enter Order"}
      </button>
    </form>
  );
}

/* ── The register of all rules ─────────────────────────────────────────────── */
function OrderRegister({
  rules,
  loaded,
  onToggle,
  onRemove,
}: {
  rules: Rule[];
  loaded: boolean;
  onToggle: (r: Rule) => void;
  onRemove: (r: Rule) => void;
}) {
  return (
    <div className="plate relative bg-card p-5">
      <div className="section-rule mb-2">
        <span className="dept-label whitespace-nowrap">The Register</span>
      </div>

      {!loaded ? (
        <p className="py-12 text-center font-sans italic text-muted-foreground">
          Reading the register…
        </p>
      ) : rules.length === 0 ? (
        <div className="grid place-items-center py-12 text-center">
          <div className="text-rule-strong/40">
            <CornerRosette size={64} seed={5} />
          </div>
          <p className="mt-3 font-display text-lg">No standing orders</p>
          <p className="mt-1 max-w-xs text-sm text-muted-foreground">
            Draft your first order at left — every posted transaction will be
            checked against it.
          </p>
        </div>
      ) : (
        <ul>
          {rules.map((rule, i) => {
            const meta = KIND_META[rule.action_type];
            const goalBound = rule.target_kind === "goal";
            return (
              <li
                key={rule.id}
                className={cn(
                  "ledger-row animate-rise-in flex items-center gap-3 py-3",
                  !rule.enabled && "opacity-55"
                )}
                style={{ animationDelay: `${Math.min(i, 6) * 50}ms` }}
              >
                <span
                  className="grid h-8 w-8 shrink-0 place-items-center border border-rule text-gold"
                  aria-hidden
                >
                  {meta.glyph}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-sans text-sm font-semibold">{rule.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{describe(rule)}</p>
                </div>

                {goalBound ? (
                  <span className="hidden shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70 sm:inline">
                    via Goal dialog
                  </span>
                ) : (
                  <div className="flex shrink-0 items-center gap-3">
                    {/* enable toggle as a ledger switch */}
                    <button
                      onClick={() => onToggle(rule)}
                      role="switch"
                      aria-checked={rule.enabled}
                      aria-label={rule.enabled ? "Suspend order" : "Activate order"}
                      className={cn(
                        "relative h-5 w-9 border transition-colors",
                        rule.enabled ? "border-credit bg-credit/20" : "border-rule bg-transparent"
                      )}
                    >
                      <span
                        className={cn(
                          "absolute top-[2px] h-3.5 w-3.5 transition-all",
                          rule.enabled ? "left-[18px] bg-credit" : "left-[2px] bg-rule-strong"
                        )}
                      />
                    </button>
                    <button
                      onClick={() => onRemove(rule)}
                      aria-label="Strike order"
                      className="font-mono text-xs text-muted-foreground transition-colors hover:text-debit"
                    >
                      ✕
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
