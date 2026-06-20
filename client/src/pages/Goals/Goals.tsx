import React, { useState, ChangeEvent, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Calendar } from "@/components/ui/calendar";
import { useReducedMotion } from "@/hooks/useEnvironment";
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
import { Plus } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { SectionRule } from "@/components/engraving/SectionRule";
import { Guilloche } from "@/components/engraving/Guilloche";
import { MintedCoin } from "@/components/custom/MintedCoin/MintedCoin";
import { RuleEditor } from "@/components/custom/RuleEditor/RuleEditor";
import ReliquaryLazy from "@/components/reliquary/ReliquaryLazy";
import { useFlags } from "@/store/gameMode";
import api from "@/lib/api";
import type { Goal } from "@/store/store";

const calculateProgress = (saved = 0, target: number) =>
  (saved / (target || 1)) * 100;

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
  const [automatedGoals, setAutomatedGoals] = useState<Record<number, boolean>>(
    {}
  );

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
  const { toast } = useToast();
  const navigate = useNavigate();
  // The collectibles Cabinet is a game-layer surface (ambient + full only).
  const { cabinet } = useFlags();
  const reduce = useReducedMotion();

  const notifyFailure = (title: string) =>
    toast({ variant: "destructive", title, description: "Please try again." });

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
    try {
      await addGoal(newGoal);
    } catch {
      notifyFailure("Could not create goal");
      return; // keep the dialog open + data intact for a retry
    }
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
    try {
      await updateGoal(selectedGoal);
    } catch {
      notifyFailure("Could not update goal");
      return;
    }
    setSelectedGoal(null);
    setEditGoalDialogOpen(false);
  };

  const handleProgressUpdate = async () => {
    if (!progressUpdateGoal?.id || progressUpdateGoal.progress === undefined)
      return;
    try {
      await updateGoalProgress(
        progressUpdateGoal.id,
        progressUpdateGoal.progress
      );
    } catch {
      notifyFailure("Could not update progress");
      return;
    }
    setProgressUpdateGoal(null);
  };

  // CRUD entry points shared by the 3D focus panel and the 2D fallback cards.
  const onEdit = (g: Goal) => {
    setSelectedGoal(g);
    setEditGoalDialogOpen(true);
  };
  const onDelete = async (g: Goal) => {
    if (!g.id) return;
    try {
      await deleteGoal(g.id);
    } catch {
      notifyFailure("Could not delete goal");
    }
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
        <ReliquaryLazy
          goals={goals}
          automatedGoals={automatedGoals}
          reduce={reduce}
          onEdit={onEdit}
          onDeposit={(g) => setProgressUpdateGoal(g)}
          onWhatIf={(g) => navigate(`/forecast?goal=${g.id}`)}
          onDelete={onDelete}
          onNew={() => setNewGoalDialogOpen(true)}
        />
      )}

      {/* Edit dialog — one instance, opened by the 3D panel or a 2D card. */}
      <Dialog
        open={editGoalDialogOpen}
        onOpenChange={(open) => {
          setEditGoalDialogOpen(open);
          if (!open) setSelectedGoal(null);
        }}
      >
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
            {selectedGoal?.id != null && (
              <RuleEditor targetKind="goal" targetId={selectedGoal.id} />
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
              onClick={async () => {
                if (!selectedGoal?.id) return;
                try {
                  await deleteGoal(selectedGoal.id);
                } catch {
                  notifyFailure("Could not delete goal");
                  return;
                }
                setEditGoalDialogOpen(false);
                setSelectedGoal(null);
              }}
              className="order-2 w-full sm:w-auto"
            >
              Delete Goal
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Deposit (saved-amount) dialog — one instance. */}
      <Dialog
        open={progressUpdateGoal != null}
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
                    prev ? { ...prev, progress: Number(e.target.value) } : null
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
            <Button onClick={handleProgressUpdate}>Update Saved Amount</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* The Cabinet — minted coins for met goals, awaiting discs for the rest.
          Game-layer collectibles (cabinet flag = ambient + full). */}
      {cabinet && goals.length > 0 && (
        <section className="mt-12">
          <SectionRule className="mb-4">The Cabinet</SectionRule>
          <div className="plate relative overflow-hidden bg-card p-8">
            <div
              aria-hidden
              className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-rule-strong/[0.06] dark:text-rule-strong/[0.1]"
            >
              <Guilloche size={520} rings={7} seed={314} animate />
            </div>
            <div className="relative flex flex-wrap justify-center gap-x-10 gap-y-8 sm:justify-start">
              {goals.map((goal) =>
                goal.completed ? (
                  <figure
                    key={goal.id}
                    className="flex w-24 flex-col items-center gap-2 text-center"
                  >
                    <MintedCoin label={goal.name} />
                    <figcaption className="font-display text-sm font-semibold leading-tight">
                      {goal.name}
                    </figcaption>
                    <span className="dept-label text-[9px]">minted</span>
                  </figure>
                ) : (
                  <figure
                    key={goal.id}
                    className="flex w-24 flex-col items-center gap-2 text-center opacity-70"
                  >
                    <span className="grid h-[84px] w-[84px] place-items-center rounded-full border border-dashed border-rule-strong/40 text-rule-strong/40">
                      <span className="font-mono text-[10px] uppercase tracking-wider">
                        {Math.round(
                          ((goal.progress || 0) / (goal.amount || 1)) * 100
                        )}
                        %
                      </span>
                    </span>
                    <figcaption className="font-display text-sm font-semibold leading-tight text-muted-foreground">
                      {goal.name}
                    </figcaption>
                    <span className="dept-label text-[9px]">awaiting</span>
                  </figure>
                )
              )}
            </div>
            <p className="serial relative mt-6 text-center font-mono text-[11px] text-muted-foreground">
              A coin is struck for each goal you complete · click one to re-strike
            </p>
          </div>
        </section>
      )}
    </>
  );
};

export default Goals;
