import React, { ChangeEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent } from "@/components/ui/card";
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
import styles from "./Budgets.module.css";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { chartColors } from "@/lib/colors";
import { formatCurrency, categoryColor } from "@/lib/format";
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

  useEffect(() => {
    fetchBudgets();
  }, [fetchBudgets]);

  const handleCreate = async () => {
    await addBudget(newBudget);
    setNewBudget(emptyForm);
    setNewDialogOpen(false);
  };

  const handleUpdate = async () => {
    if (!editBudget) return;
    await updateBudget(editBudget.id, {
      category: editBudget.category,
      monthly_limit: editBudget.monthly_limit,
      rollover: editBudget.rollover,
    });
    setEditBudget(null);
  };

  const handleDelete = async (id: number) => {
    await deleteBudget(id);
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
        description="Track spending against your monthly limits."
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
        <div className="flex h-64 items-center justify-center text-muted-foreground">
          Loading budgets...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
          {budgets.map((b) => {
            const color = categoryColor(b.category, chartColors.primary);
            return (
              <Card
                key={b.id}
                className={`${styles.budgetCard} group relative cursor-pointer hover:opacity-95`}
                onClick={() => setEditBudget(b)}
              >
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute right-2 top-2 z-10 h-8 w-8 p-0 opacity-0 transition-opacity group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(b.id);
                  }}
                >
                  <Trash2 className="text-destructive" size={20} />
                </Button>
                <CardContent className="pt-6">
                  <div className="mb-2 flex items-center gap-2">
                    <span
                      className="inline-block h-3 w-3 rounded-full"
                      style={{ backgroundColor: color }}
                    />
                    <h2 className="text-xl font-semibold">{b.category}</h2>
                  </div>
                  <Progress value={progressPercent(b)} className="my-3 w-full" />
                  <p className="mb-1 text-sm text-muted-foreground">
                    {formatCurrency(b.spent)} spent of{" "}
                    {formatCurrency(b.effective_limit)}
                  </p>
                  <p
                    className={`text-sm font-medium ${
                      b.over_budget
                        ? "text-destructive"
                        : b.on_pace
                        ? "text-success"
                        : "text-orange-500"
                    }`}
                  >
                    {b.over_budget
                      ? `${formatCurrency(Math.abs(b.remaining))} over budget`
                      : `${formatCurrency(b.remaining)} remaining`}
                  </p>
                  {b.rollover && b.effective_limit !== b.monthly_limit && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Includes{" "}
                      {formatCurrency(b.effective_limit - b.monthly_limit)} rolled
                      over
                    </p>
                  )}
                </CardContent>
              </Card>
            );
          })}
          {budgets.length === 0 && (
            <div className="col-span-full flex min-h-[40vh] items-center justify-center text-xl text-muted-foreground">
              You don't have any budgets yet...
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
