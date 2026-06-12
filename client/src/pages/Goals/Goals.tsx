import React, { useState, ChangeEvent, useEffect } from "react";
import { Calendar } from "@/components/ui/calendar";
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
import { Textarea } from "@/components/ui/textarea";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { Certificate } from "@/components/engraving/Certificate";
import { Seal } from "@/components/engraving/Seal";
import { RuleEditor } from "@/components/custom/RuleEditor/RuleEditor";
import api from "@/lib/api";
import type { Goal } from "@/store/store";

const Goals: React.FC = () => {
  const [newGoal, setNewGoal] = useState<Omit<Goal, "id">>({
    name: "",
    description: "",
    amount: 0,
    progress: 0,
    deadline: new Date(),
    completed: false,
  });
  const [selectedGoal, setSelectedGoal] = useState<Goal | null>(null);
  const [progressUpdateGoal, setProgressUpdateGoal] = useState<Goal | null>(
    null
  );
  const [newGoalDialogOpen, setNewGoalDialogOpen] = useState(false);
  const [editGoalDialogOpen, setEditGoalDialogOpen] = useState(false);
  // Which goals have auto-fund rules (goal id → true) for the ⟳ badge.
  const [automatedGoals, setAutomatedGoals] = useState<Record<number, boolean>>({});

  const {
    goals,
    goalsLoaded,
    isLoading,
    fetchGoals,
    addGoal,
    updateGoal,
    deleteGoal,
    updateGoalProgress,
  } = useStore();

  useEffect(() => {
    fetchGoals();
  }, [fetchGoals]);

  // Badge data: which goals are automated (one fetch, grouped client-side).
  useEffect(() => {
    let cancelled = false;
    api
      .get("/rules/", { params: { target_kind: "goal" } })
      .then(({ data }) => {
        if (cancelled) return;
        const map: Record<number, boolean> = {};
        for (const rule of data) {
          if (rule.target_id != null) map[rule.target_id] = true;
        }
        setAutomatedGoals(map);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [goals]);

  const handleCreateGoal = async () => {
    await addGoal(newGoal);
    setNewGoal({
      name: "",
      description: "",
      amount: 0,
      progress: 0,
      deadline: new Date(),
      completed: false,
    });
    setNewGoalDialogOpen(false);
  };

  const handleUpdateGoal = async () => {
    if (!selectedGoal?.id) return;
    await updateGoal(selectedGoal);
    setSelectedGoal(null);
    setEditGoalDialogOpen(false);
  };

  const handleProgressUpdate = async () => {
    if (!progressUpdateGoal?.id || progressUpdateGoal.progress === undefined)
      return;
    await updateGoalProgress(progressUpdateGoal.id, progressUpdateGoal.progress);
    setProgressUpdateGoal(null);
  };

  const calculateProgress = (savedAmount: number = 0, targetAmount: number) =>
    (savedAmount / targetAmount) * 100;

  const getDeadlineStatus = (deadline: Date) => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const deadlineDate = new Date(deadline);
    deadlineDate.setHours(0, 0, 0, 0);

    const diffDays = Math.ceil(
      (deadlineDate.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)
    );

    if (diffDays < 0) return { color: "text-destructive", text: "Past due" };
    if (diffDays === 0) return { color: "text-destructive", text: "Due today" };
    if (diffDays <= 3) {
      return {
        color: "text-orange-500",
        text: `${diffDays} day${diffDays === 1 ? "" : "s"} left`,
      };
    }
    return {
      color: "text-muted-foreground",
      text: deadlineDate.toLocaleDateString(),
    };
  };

  const newGoalDialog = (
    <Dialog open={newGoalDialogOpen} onOpenChange={setNewGoalDialogOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          New Goal
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create New Savings Goal</DialogTitle>
          <DialogDescription>
            Set up a new savings goal with a target amount and deadline.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={newGoal.name}
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                setNewGoal({ ...newGoal, name: e.target.value })
              }
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={newGoal.description}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                setNewGoal({ ...newGoal, description: e.target.value })
              }
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="amount">Amount</Label>
            <Input
              id="amount"
              type="number"
              value={newGoal.amount}
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                setNewGoal({ ...newGoal, amount: Number(e.target.value) })
              }
            />
          </div>
          <div className="grid gap-2">
            <Label>Deadline</Label>
            <Calendar
              mode="single"
              selected={newGoal.deadline}
              onSelect={(date) => {
                if (date) setNewGoal({ ...newGoal, deadline: date });
              }}
              className="rounded-md border"
              disabled={(date) =>
                date < new Date(new Date().setHours(0, 0, 0, 0))
              }
            />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={handleCreateGoal}>Create Goal</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );

  return (
    <>
      <PageHeader
        title="Goals"
        description="Savings subscriptions, sealed upon completion."
        reference="Folio V · Sinking Funds"
        actions={newGoalDialog}
      />

      {isLoading && !goalsLoaded ? (
        <div className="flex h-64 items-center justify-center text-muted-foreground">
          Loading goals...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
          {goals.map((goal) => (
            <div key={goal.id} className="w-full">
              <Dialog
                open={editGoalDialogOpen && selectedGoal?.id === goal.id}
                onOpenChange={(open) => {
                  setEditGoalDialogOpen(open);
                  setSelectedGoal(open ? goal : null);
                }}
              >
                <DialogTrigger asChild>
                  <Certificate seed={(goal.id ?? 1) * 17 + 3} className="h-full">
                    <button
                      aria-label="Delete goal"
                      className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center text-muted-foreground opacity-0 transition-opacity hover:text-debit group-hover:opacity-100"
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!goal.id) return;
                        await deleteGoal(goal.id);
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
                          <Seal label="Goal · Met · Goal · Met" size={56} tone="approved" pulse />
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

                      <div className="relative mb-1 h-2 w-full overflow-hidden border border-rule-strong/40 bg-secondary">
                        <div
                          className="absolute inset-y-0 left-0 bg-credit transition-[width] duration-700 ease-out"
                          style={{
                            width: `${Math.min(
                              100,
                              calculateProgress(goal.progress || 0, goal.amount)
                            )}%`,
                          }}
                        />
                      </div>
                      <p className="mb-4 text-right font-mono text-[11px] text-muted-foreground">
                        {calculateProgress(goal.progress || 0, goal.amount).toFixed(0)}% subscribed
                      </p>

                      <div className="flex items-center justify-between border-t border-rule pt-3">
                        <p className={`flex items-center gap-1.5 font-mono text-[11px] ${getDeadlineStatus(goal.deadline).color}`}>
                          Matures {getDeadlineStatus(goal.deadline).text}
                          {goal.id != null && automatedGoals[goal.id] && (
                            <span
                              className="flex items-center gap-0.5 text-credit"
                              title="Auto-funded by a rule"
                            >
                              <RefreshCw size={10} /> auto
                            </span>
                          )}
                        </p>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setProgressUpdateGoal(goal);
                          }}
                        >
                          Deposit
                        </Button>
                      </div>
                    </div>
                  </Certificate>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Edit Goal</DialogTitle>
                    <DialogDescription>
                      Update your savings goal details.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                      <Label htmlFor="edit-name">Name</Label>
                      <Input
                        id="edit-name"
                        value={selectedGoal?.name || ""}
                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                          setSelectedGoal((prev) =>
                            prev ? { ...prev, name: e.target.value } : null
                          )
                        }
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="edit-description">Description</Label>
                      <Textarea
                        id="edit-description"
                        value={selectedGoal?.description || ""}
                        onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                          setSelectedGoal((prev) =>
                            prev ? { ...prev, description: e.target.value } : null
                          )
                        }
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="edit-amount">Amount</Label>
                      <Input
                        id="edit-amount"
                        type="number"
                        value={selectedGoal?.amount || 0}
                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                          setSelectedGoal((prev) =>
                            prev ? { ...prev, amount: Number(e.target.value) } : null
                          )
                        }
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label>Deadline</Label>
                      <Calendar
                        mode="single"
                        selected={selectedGoal?.deadline}
                        onSelect={(date) => {
                          if (date)
                            setSelectedGoal((prev) =>
                              prev ? { ...prev, deadline: date } : null
                            );
                        }}
                        className="rounded-md border"
                        disabled={(date) =>
                          date < new Date(new Date().setHours(0, 0, 0, 0))
                        }
                      />
                    </div>
                    {/* Auto-fund: the embedded rule editor, target pre-bound */}
                    {goal.id != null && (
                      <RuleEditor targetKind="goal" targetId={goal.id} />
                    )}
                  </div>
                  <DialogFooter className="flex flex-col gap-2 sm:flex-row">
                    <Button
                      onClick={handleUpdateGoal}
                      className="order-1 w-full sm:w-auto"
                    >
                      Update Goal
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!selectedGoal?.id) return;
                        await deleteGoal(selectedGoal.id);
                        setEditGoalDialogOpen(false);
                      }}
                      className="order-2 w-full sm:w-auto"
                    >
                      Delete Goal
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              <Dialog
                open={progressUpdateGoal?.id === goal.id}
                onOpenChange={(open) => {
                  if (!open) setProgressUpdateGoal(null);
                }}
              >
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Update Saved Amount</DialogTitle>
                    <DialogDescription>
                      Update how much you've saved towards this goal.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                      <Label htmlFor="progress">Amount Saved ($)</Label>
                      <Input
                        id="progress"
                        type="number"
                        min="0"
                        max={progressUpdateGoal?.amount}
                        value={progressUpdateGoal?.progress || 0}
                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                          setProgressUpdateGoal((prev) =>
                            prev
                              ? { ...prev, progress: Number(e.target.value) }
                              : null
                          )
                        }
                      />
                      <p className="text-sm text-muted-foreground">
                        {progressUpdateGoal
                          ? `${calculateProgress(
                              progressUpdateGoal.progress || 0,
                              progressUpdateGoal.amount
                            ).toFixed(1)}% of goal`
                          : null}
                      </p>
                    </div>
                  </div>
                  <DialogFooter>
                    <Button onClick={handleProgressUpdate}>
                      Update Saved Amount
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          ))}
          {goals.length === 0 && (
            <div className="col-span-full flex min-h-[40vh] flex-col items-center justify-center gap-4">
              <p className="font-mono text-sm text-muted-foreground">
                No savings goals yet.
              </p>
              <Button onClick={() => setNewGoalDialogOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                Create your first goal
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  );
};

export default Goals;
