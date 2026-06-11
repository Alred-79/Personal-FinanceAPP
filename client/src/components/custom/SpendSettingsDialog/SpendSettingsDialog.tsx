import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useState, useEffect } from "react";
import { SettingsIcon } from "lucide-react";
import { useStore } from "@/store/store";
import styles from "./SpendSettingsDialog.module.css";

interface SpendSettingsDialogProps {
  onWarningPositionChange: (position: number) => void;
  onSavingsPercentChange: (savingsPercent: number) => void;
}

export function SpendSettingsDialog({
  onWarningPositionChange,
  onSavingsPercentChange,
}: SpendSettingsDialogProps) {
  const [open, setOpen] = useState(false);

  const {
    warningPosition,
    savingsPercent,
    settingsLoaded,
    fetchUserSettings,
    updateWarningPosition,
    updateSavingsPercent,
  } = useStore();

  const [position, setPosition] = useState(warningPosition);
  const [savings, setSavings] = useState(savingsPercent);

  // Load settings on first mount if not already loaded
  useEffect(() => {
    if (!settingsLoaded) {
      fetchUserSettings();
    }
  }, [settingsLoaded, fetchUserSettings]);

  // Update local state when store values change
  useEffect(() => {
    setPosition(warningPosition);
    setSavings(savingsPercent);
  }, [warningPosition, savingsPercent]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateWarningPosition(position);
      await updateSavingsPercent(savings);
      onWarningPositionChange(position);
      onSavingsPercentChange(savings);
      setOpen(false);
    } catch (error) {
      console.error("Failed to update settings:", error);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className={styles.settingsButton}>
          <SettingsIcon />
        </Button>
      </DialogTrigger>
      <DialogContent
        className={`${styles.dialogContent} md:!scale-100 !scale-[0.85] !origin-center md:translate-y-0 !-translate-y-[200%]`}
      >
        <DialogHeader>
          <DialogTitle>Spend Settings</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.inputGroup}>
            <Label htmlFor="warning-position">Spend Warning Percent (%)</Label>
            <Input
              id="warning-position"
              type="number"
              min="0"
              max="100"
              value={position}
              onChange={(e) => setPosition(Number(e.target.value))}
              required
            />
            <p className={styles.helpText}>
              The percentage of the budget used that will warn against any
              further spending.
            </p>
          </div>
          <div className={styles.inputGroup}>
            <Label htmlFor="savings-percent">Savings Percent (%)</Label>
            <Input
              id="savings-percent"
              type="number"
              min="0"
              max="100"
              value={savings}
              onChange={(e) => setSavings(Number(e.target.value))}
              required
            />
            <p className={styles.helpText}>
              The percentage of money that will be saved each month and
              automatically deducted from your budget.
            </p>
          </div>
          <Button type="submit" className={styles.submitButton}>
            Save Settings
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
