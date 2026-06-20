import { Trash2, RefreshCw, Plus } from "lucide-react";
import type { Goal } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Certificate } from "@/components/engraving/Certificate";
import { Seal } from "@/components/engraving/Seal";
import { EmptyState } from "@/components/engraving/EmptyState";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { JarBar } from "./JarBar";

export interface ReliquaryProps {
  goals: Goal[];
  automatedGoals: Record<number, boolean>;
  reduce: boolean;
  onEdit: (g: Goal) => void;
  onDeposit: (g: Goal) => void;
  onWhatIf: (g: Goal) => void;
  onDelete: (g: Goal) => void;
  onNew: () => void;
}

const pct = (saved = 0, target = 1) => (saved / (target || 1)) * 100;

function deadlineStatus(deadline: Date) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(deadline);
  d.setHours(0, 0, 0, 0);
  const days = Math.ceil((d.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return { color: "text-destructive", text: "Past due" };
  if (days === 0) return { color: "text-destructive", text: "Due today" };
  if (days <= 3)
    return {
      color: "text-orange-500",
      text: `${days} day${days === 1 ? "" : "s"} left`,
    };
  return { color: "text-muted-foreground", text: d.toLocaleDateString() };
}

/**
 * The elevated-2D goal vault: engraved Certificate cards with a segmented
 * earmark JarBar. The off-mode / no-WebGL / Suspense-fallback render of the
 * Reliquary — every CRUD affordance routes through the page-level handlers, so
 * behaviour matches the 3D focus panel exactly.
 */
export default function ReliquaryFlat({
  goals,
  automatedGoals,
  reduce,
  onEdit,
  onDeposit,
  onWhatIf,
  onDelete,
  onNew,
}: ReliquaryProps) {
  if (goals.length === 0) {
    return (
      <EmptyState
        seed={20}
        eyebrow="Goals · A dark sky"
        title="Awaiting its first star"
        description="You haven't charted a destination yet. Set a goal and watch its vessel fill as you approach — saving you'll actually want to finish."
        action={
          <Button onClick={onNew}>
            <Plus className="mr-2 h-4 w-4" />
            Chart your first goal
          </Button>
        }
      />
    );
  }

  return (
    <Reveal className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
      {goals.map((goal) => {
        const status = deadlineStatus(goal.deadline);
        return (
          <RevealItem key={goal.id} className="h-full">
            <Certificate
              seed={(goal.id ?? 1) * 17 + 3}
              alive
              className="group h-full cursor-pointer"
              onClick={() => onEdit(goal)}
            >
              <button
                aria-label="Delete goal"
                className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center text-muted-foreground opacity-0 transition-opacity hover:text-debit group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(goal);
                }}
              >
                <Trash2 size={17} />
              </button>

              <div className="p-6">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="dept-label">Certificate of Savings</p>
                    <h2 className="font-display text-xl font-semibold leading-tight">
                      {goal.name}
                    </h2>
                  </div>
                  {goal.completed && (
                    <Seal
                      label="Goal · Met · Goal · Met"
                      size={56}
                      tone="approved"
                      pulse
                    />
                  )}
                </div>

                <p className="mb-5 line-clamp-2 font-sans text-sm italic text-muted-foreground">
                  {goal.description || "—"}
                </p>

                <div className="mb-2 flex items-baseline justify-between">
                  <span className="intaglio text-2xl text-foreground">
                    {formatCurrency(goal.progress || 0)}
                  </span>
                  <span className="ledger-figures text-xs text-muted-foreground">
                    of {formatCurrency(goal.amount)}
                  </span>
                </div>

                <JarBar
                  progress={goal.progress || 0}
                  amount={goal.amount}
                  earmarks={goal.earmarks ?? []}
                  reduce={reduce}
                />
                <p className="mb-4 mt-1 text-right font-mono text-[11px] text-muted-foreground">
                  {pct(goal.progress || 0, goal.amount).toFixed(0)}% subscribed
                </p>

                <div className="flex items-center justify-between border-t border-rule pt-3">
                  <p
                    className={`flex items-center gap-1.5 font-mono text-[11px] ${status.color}`}
                  >
                    Matures {status.text}
                    {goal.id != null && automatedGoals[goal.id] && (
                      <span
                        className="flex items-center gap-0.5 text-credit"
                        title="Auto-funded by a rule"
                      >
                        <RefreshCw size={10} /> auto
                      </span>
                    )}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label="What if"
                      onClick={(e) => {
                        e.stopPropagation();
                        onWhatIf(goal);
                      }}
                    >
                      What if…
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeposit(goal);
                      }}
                    >
                      Deposit
                    </Button>
                  </div>
                </div>
              </div>
            </Certificate>
          </RevealItem>
        );
      })}
    </Reveal>
  );
}
