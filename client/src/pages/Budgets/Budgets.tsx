import React, { ChangeEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Plus, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { chartColors } from "@/lib/colors";
import { formatCurrency, categoryColor } from "@/lib/format";
import { categoryIcon } from "@/lib/categoryIcon";
import { Certificate } from "@/components/engraving/Certificate";
import { Stamp } from "@/components/engraving/Stamp";
import type { Budget } from "@/store/store";

type BudgetForm = {
  category: string;
  monthly_limit: number;
  rollover: boolean;
};

const emptyForm: BudgetForm = {
  category: "",
  monthly_limit: 0,
  rollover: false,
};

const Budgets: React.FC = () => {
  const { budgets, budgetsLoaded, isLoading, fetchBudgets, addBudget, updateBudget, deleteBudget } =
    useStore();

  const [newDialogOpen, setNewDialogOpen] = useState(false);
  const [newBudget, setNewBudget] = useState<BudgetForm>(emptyForm);
  const [editBudget, setEditBudget] = useState<Budget | null>(null);
  const { toast } = useToast();

  // The budget store actions rethrow on failure; catch so the failure is
  // surfaced (and the dialog stays open on the data) instead of an unhandled
  // rejection that silently closes the form as if the save worked.
  const notifyFailure = (title: string) =>
    toast({ variant: "destructive", title, description: "Please try again." });

  useEffect(() => {
    fetchBudgets();
  }, [fetchBudgets]);

  const handleCreate = async () => {
    try {
      await addBudget(newBudget);
    } catch {
      notifyFailure("Could not create budget");
      return;
    }
    setNewBudget(emptyForm);
    setNewDialogOpen(false);
  };

  const handleUpdate = async () => {
    if (!editBudget) return;
    try {
      await updateBudget(editBudget.id, {
        category: editBudget.category,
        monthly_limit: editBudget.monthly_limit,
        rollover: editBudget.rollover,
      });
    } catch {
      notifyFailure("Could not update budget");
      return;
    }
    setEditBudget(null);
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteBudget(id);
    } catch {
      notifyFailure("Could not delete budget");
      return;
    }
    setEditBudget(null);
  };

  const progressPercent = (b: Budget) => {
    if (b.effective_limit <= 0) return 0;
    return Math.min(100, (b.spent / b.effective_limit) * 100);
  };

  return (
    <>
      <PageHeader
        title="Budgets"
        description="Envelopes ruled against your monthly limits."
        reference="Folio IV · Appropriations"
        actions={
          <Dialog open={newDialogOpen} onOpenChange={setNewDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                New Budget
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Budget</DialogTitle>
                <DialogDescription>
                  Set a monthly spending limit for a category.
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid gap-2">
                  <Label htmlFor="category">Category</Label>
                  <Input
                    id="category"
                    placeholder="e.g. Food"
                    value={newBudget.category}
                    onChange={(e: ChangeEvent<HTMLInputElement>) =>
                      setNewBudget({ ...newBudget, category: e.target.value })
                    }
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="limit">Monthly Limit ($)</Label>
                  <Input
                    id="limit"
                    type="number"
                    min="0"
                    value={newBudget.monthly_limit}
                    onChange={(e: ChangeEvent<HTMLInputElement>) =>
                      setNewBudget({
                        ...newBudget,
                        monthly_limit: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="rollover">Roll over unused funds</Label>
                  <Switch
                    id="rollover"
                    checked={newBudget.rollover}
                    onCheckedChange={(checked) =>
                      setNewBudget({ ...newBudget, rollover: checked })
                    }
                  />
                </div>
              </div>
              <DialogFooter>
                <Button onClick={handleCreate} disabled={!newBudget.category}>
                  Create Budget
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      {isLoading && !budgetsLoaded ? (
        <div className="flex h-64 items-center justify-center font-sans italic text-muted-foreground">
          Counting the envelopes…
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
          {budgets.map((b, i) => {
            const color = categoryColor(b.category, chartColors.primary);
            const Icon = categoryIcon(b.category);
            const pct = progressPercent(b);
            const fill = b.over_budget
              ? "hsl(var(--debit))"
              : b.on_pace
              ? "hsl(var(--credit))"
              : "hsl(var(--gold))";
            return (
              <Certificate
                key={b.id}
                seed={b.id * 13 + 1}
                accent={color}
                onClick={() => setEditBudget(b)}
                className="animate-rise-in"
              >
                <div style={{ animationDelay: `${i * 50}ms` }} className="p-6">
                  <button
                    aria-label="Delete budget"
                    className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center text-muted-foreground opacity-0 transition-opacity hover:text-debit group-hover:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(b.id);
                    }}
                  >
                    <Trash2 size={17} />
                  </button>

                  <div className="mb-4 flex items-center gap-3">
                    <span
                      className="grid h-10 w-10 shrink-0 place-items-center border border-rule-strong/40 bg-card"
                      style={{ color }}
                    >
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <p className="dept-label">Appropriation</p>
                      <h2 className="font-display text-xl font-semibold leading-tight">
                        {b.category}
                      </h2>
                    </div>
                  </div>

                  <div className="mb-3 flex items-baseline justify-between">
                    <span className="intaglio text-2xl text-foreground">
                      {formatCurrency(b.spent)}
                    </span>
                    <span className="ledger-figures text-xs text-muted-foreground">
                      of {formatCurrency(b.effective_limit)}
                    </span>
                  </div>

                  <div className="relative h-2 w-full overflow-hidden border border-rule-strong/40 bg-secondary">
                    <div
                      className="absolute inset-y-0 left-0 transition-[width] duration-700 ease-out"
                      style={{ width: `${pct}%`, background: fill }}
                    />
                  </div>

                  <div className="mt-3 flex items-center justify-between">
                    <p
                      className="font-sans text-sm font-medium"
                      style={{ color: fill }}
                    >
                      {b.over_budget
                        ? `${formatCurrency(Math.abs(b.remaining))} over`
                        : `${formatCurrency(b.remaining)} left`}
                    </p>
                    {b.over_budget ? (
                      <Stamp variant="debit" still>
                        Over Budget
                      </Stamp>
                    ) : b.on_pace ? (
                      <Stamp variant="credit" still>
                        On Pace
                      </Stamp>
                    ) : (
                      <Stamp variant="gold" still>
                        Watch
                      </Stamp>
                    )}
                  </div>

                  {b.rollover && b.effective_limit !== b.monthly_limit && (
                    <p className="mt-2 font-sans text-[11px] italic text-muted-foreground">
                      incl. {formatCurrency(b.effective_limit - b.monthly_limit)}{" "}
                      rolled over
                    </p>
                  )}
                </div>
              </Certificate>
            );
          })}
          {budgets.length === 0 && (
            <div className="col-span-full flex min-h-[40vh] flex-col items-center justify-center gap-3">
              <p className="font-display text-2xl text-muted-foreground">
                No envelopes ruled yet
              </p>
              <p className="font-sans text-sm italic text-muted-foreground">
                Rule your first budget to begin appropriating funds.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Edit dialog */}
      <Dialog
        open={editBudget !== null}
        onOpenChange={(open) => {
          if (!open) setEditBudget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Budget</DialogTitle>
            <DialogDescription>
              Update the monthly limit for this category.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="edit-category">Category</Label>
              <Input
                id="edit-category"
                value={editBudget?.category || ""}
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  setEditBudget((prev) =>
                    prev ? { ...prev, category: e.target.value } : null
                  )
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="edit-limit">Monthly Limit ($)</Label>
              <Input
                id="edit-limit"
                type="number"
                min="0"
                value={editBudget?.monthly_limit ?? 0}
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  setEditBudget((prev) =>
                    prev
                      ? { ...prev, monthly_limit: Number(e.target.value) }
                      : null
                  )
                }
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="edit-rollover">Roll over unused funds</Label>
              <Switch
                id="edit-rollover"
                checked={editBudget?.rollover ?? false}
                onCheckedChange={(checked) =>
                  setEditBudget((prev) =>
                    prev ? { ...prev, rollover: checked } : null
                  )
                }
              />
            </div>
          </div>
          <DialogFooter className="flex flex-col gap-2 sm:flex-row">
            <Button onClick={handleUpdate} className="order-1 w-full sm:w-auto">
              Save Changes
            </Button>
            <Button
              variant="destructive"
              onClick={() => editBudget && handleDelete(editBudget.id)}
              className="order-2 w-full sm:w-auto"
            >
              Delete Budget
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default Budgets;
