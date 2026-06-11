import React, { useState, ChangeEvent, useEffect } from "react";
import { Calendar } from "@/components/ui/calendar";
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
import { Textarea } from "@/components/ui/textarea";
import styles from "./Goals.module.css";
import { Plus, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
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
        description="Set savings targets and track your progress."
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
                  <Card
                    className={`${styles.goalCard} group relative cursor-pointer hover:opacity-95`}
                  >
                    <Button
                      variant="ghost"
                      size="icon"
                      className="absolute right-2 top-2 z-10 h-8 w-8 p-0 opacity-0 transition-opacity group-hover:opacity-100"
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!goal.id) return;
                        await deleteGoal(goal.id);
                      }}
                    >
                      <Trash2 className="text-destructive" size={20} />
                    </Button>
                    <CardContent className="pt-6">
                      <h2 className="mb-2 text-xl font-semibold">{goal.name}</h2>
                      <p className="mb-4 text-muted-foreground">
                        {goal.description}
                      </p>
                      <div className="mb-2 flex w-full flex-col gap-2 md:flex-row md:items-center">
                        <div className="w-full">
                          <Progress
                            value={calculateProgress(
                              goal.progress || 0,
                              goal.amount
                            )}
                            className="w-full"
                          />
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-10 w-full whitespace-nowrap md:h-8 md:w-auto"
                          onClick={(e) => {
                            e.stopPropagation();
                            setProgressUpdateGoal(goal);
                          }}
                        >
                          Update Progress
                        </Button>
                      </div>
                      <p className="mb-1 text-sm text-muted-foreground">
                        ${(goal.progress || 0).toLocaleString()} saved of $
                        {goal.amount.toLocaleString()}
                      </p>
                      <p className={`text-sm ${getDeadlineStatus(goal.deadline).color}`}>
                        Deadline: {getDeadlineStatus(goal.deadline).text}
                      </p>
                    </CardContent>
                  </Card>
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
