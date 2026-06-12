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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useState, useEffect } from "react";
import { SettingsIcon } from "lucide-react";
import { useStore } from "@/store/store";
import styles from "./SpendSettingsDialog.module.css";

interface SpendSettingsDialogProps {
  onWarningPositionChange: (position: number) => void;
  onSavingsPercentChange: (savingsPercent: number) => void;
}

/**
 * SafeToSpend.Settings — the gear behind the one number, sectioned into
 * *Horizon* (what the number is measured against), *What counts* (which
 * components move it), and *Savings* (the original warning/savings knobs).
 * One dialog; no settings page.
 */
export function SpendSettingsDialog({
  onWarningPositionChange,
  onSavingsPercentChange,
}: SpendSettingsDialogProps) {
  const [open, setOpen] = useState(false);

  const {
    warningPosition,
    savingsPercent,
    s2sPrefs,
    settingsLoaded,
    fetchUserSettings,
    updateWarningPosition,
    updateSavingsPercent,
    updateS2sPrefs,
  } = useStore();

  const [position, setPosition] = useState(warningPosition);
  const [savings, setSavings] = useState(savingsPercent);
  const [horizon, setHorizon] = useState(s2sPrefs.s2s_horizon);
  const [includeIncome, setIncludeIncome] = useState(s2sPrefs.s2s_include_income);
  const [includeGoals, setIncludeGoals] = useState(s2sPrefs.s2s_include_goals);
  const [buffer, setBuffer] = useState(s2sPrefs.s2s_buffer);

  useEffect(() => {
    if (!settingsLoaded) {
      fetchUserSettings();
    }
  }, [settingsLoaded, fetchUserSettings]);

  useEffect(() => {
    setPosition(warningPosition);
    setSavings(savingsPercent);
    setHorizon(s2sPrefs.s2s_horizon);
    setIncludeIncome(s2sPrefs.s2s_include_income);
    setIncludeGoals(s2sPrefs.s2s_include_goals);
    setBuffer(s2sPrefs.s2s_buffer);
  }, [warningPosition, savingsPercent, s2sPrefs]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateWarningPosition(position);
      await updateSavingsPercent(savings);
      await updateS2sPrefs({
        s2s_horizon: horizon,
        s2s_include_income: includeIncome,
        s2s_include_goals: includeGoals,
        s2s_buffer: buffer,
      });
      onWarningPositionChange(position);
      onSavingsPercentChange(savings);
      setOpen(false);
    } catch (error) {
      console.error("Failed to update settings:", error);
    }
  };

  const sectionTitle = (text: string) => (
    <p className="border-b border-rule pb-1 font-sans text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
      {text}
    </p>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className={styles.settingsButton}>
          <SettingsIcon />
        </Button>
      </DialogTrigger>
      <DialogContent
        className={`${styles.dialogContent} md:!scale-100 !scale-[0.85] !origin-center max-h-[85vh] overflow-y-auto`}
      >
        <DialogHeader>
          <DialogTitle>Safe-to-Spend Settings</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className={styles.form}>
          {/* ── Horizon ─────────────────────────────────────────────── */}
          {sectionTitle("Horizon")}
          <div className={styles.inputGroup}>
            <Label htmlFor="s2s-horizon">Measure until</Label>
            <Select
              value={horizon}
              onValueChange={(v) => setHorizon(v as typeof horizon)}
            >
              <SelectTrigger id="s2s-horizon">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="paycheck">Next paycheck</SelectItem>
                <SelectItem value="month">End of month</SelectItem>
                <SelectItem value="week">One week</SelectItem>
              </SelectContent>
            </Select>
            <p className={styles.helpText}>
              The number is what's safe to spend between now and this point.
              "Next paycheck" needs a recurring income; it falls back to end of
              month otherwise.
            </p>
          </div>

          {/* ── What counts ────────────────────────────────────────── */}
          {sectionTitle("What counts")}
          <div className="flex items-center gap-2">
            <Checkbox
              id="s2s-income"
              checked={includeIncome}
              onCheckedChange={(c) => setIncludeIncome(c as boolean)}
            />
            <Label htmlFor="s2s-income">Add projected income</Label>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="s2s-goals"
              checked={includeGoals}
              onCheckedChange={(c) => setIncludeGoals(c as boolean)}
            />
            <Label htmlFor="s2s-goals">Subtract goal earmarks</Label>
          </div>
          <div className={styles.inputGroup}>
            <Label htmlFor="s2s-buffer">Buffer ($ held back)</Label>
            <Input
              id="s2s-buffer"
              type="number"
              min="0"
              step="1"
              value={buffer}
              onChange={(e) => setBuffer(Number(e.target.value))}
            />
          </div>

          {/* ── Savings ────────────────────────────────────────────── */}
          {sectionTitle("Savings")}
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
