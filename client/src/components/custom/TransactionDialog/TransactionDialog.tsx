import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useState, useEffect } from "react";
import styles from "./TransactionDialog.module.css";
import { TransactionDialogProps, Frequency, ReceiptDraft } from "@/types";
import { useStore } from "@/store/store";
import { CATEGORIES } from "@/lib/colors";
import { normalizeDraftCategory } from "@/lib/receipt";
import { ReceiptDropzone } from "./ReceiptDropzone";

const today = () => new Date().toISOString().split("T")[0];

export function TransactionDialog({
  onSubmit,
  open: controlledOpen,
  onOpenChange,
  initialDraft,
  trigger,
}: TransactionDialogProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;
  const setOpen = (value: boolean) => {
    if (!isControlled) setInternalOpen(value);
    onOpenChange?.(value);
  };

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(today());
  const [category, setCategory] = useState("");
  const [isIncome, setIsIncome] = useState(false);
  const [recurrence, setRecurrence] = useState<string>();
  const [selectedAccount, setSelectedAccount] = useState<string>();
  const [scanning, setScanning] = useState(false);

  const { accounts, fetchAccounts } = useStore();

  // Prefill the form from a scanned receipt (whether the draft arrives via the
  // in-dialog dropzone or is passed in by an external quick-action). Account is
  // intentionally left for the user — a receipt can't tell us which one.
  const applyDraft = (draft: ReceiptDraft) => {
    setTitle(draft.title ?? draft.merchant ?? "");
    setAmount(draft.amount != null ? String(draft.amount) : "");
    setDate(draft.date ?? today());
    setCategory(normalizeDraftCategory(draft.category));
  };

  useEffect(() => {
    if (initialDraft) applyDraft(initialDraft);
  }, [initialDraft]);

  useEffect(() => {
    // Fetch accounts when dialog opens
    if (open) {
      fetchAccounts();
    }
  }, [open, fetchAccounts]);

  useEffect(() => {
    // Clear the form on close so the next open (e.g. a manual "New Transaction"
    // after a scan) starts blank rather than reusing stale receipt values.
    if (!open) {
      setTitle("");
      setAmount("");
      setDate(today());
      setCategory("");
      setIsIncome(false);
      setRecurrence(undefined);
      setSelectedAccount(undefined);
    }
  }, [open]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Validate required fields
    if (!title.trim() || !amount || !category || !selectedAccount) {
      return;
    }

    onSubmit({
      title,
      amount: parseFloat(amount),
      date,
      category,
      isIncome,
      account_id: parseInt(selectedAccount),
      recurrence: recurrence as Frequency | undefined,
    });
    setOpen(false);
    // Reset form
    setTitle("");
    setAmount("");
    setDate(today());
    setCategory("");
    setIsIncome(false);
    setRecurrence(undefined);
    setSelectedAccount(undefined);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button className={styles.newTransactionButton}>
            New Transaction
          </Button>
        )}
      </DialogTrigger>
      <DialogContent
        className={`${styles.transactionDialog} md:scale-100 scale-[0.7] origin-center`}
      >
        <DialogHeader>
          <DialogTitle>Add New Transaction</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className={styles.formContainer}>
          <ReceiptDropzone onScanned={applyDraft} onScanning={setScanning} />
          <div className={styles.orDivider}>— or enter manually —</div>
          <div className={styles.checkboxContainer}>
            <div className={styles.checkboxWrapper}>
              <Checkbox
                id="income-mode"
                checked={isIncome}
                onCheckedChange={(checked) => setIsIncome(checked as boolean)}
                className={styles.incomeCheckbox}
              />
              <Label
                htmlFor="income-mode"
                className={isIncome ? "text-credit" : undefined}
              >
                Income
              </Label>
            </div>
            {/* Recurrence applies to income too (v1): a recurring paycheck is
                what anchors the forecast and the Safe-to-Spend horizon. */}
            <div className={styles.selectContainer}>
              <Select
                value={recurrence}
                onValueChange={(value) =>
                  setRecurrence(value === "unset" ? undefined : value)
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select frequency (optional)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="unset">Not recurring</SelectItem>
                  <SelectItem value="daily">Daily</SelectItem>
                  <SelectItem value="weekly">Weekly</SelectItem>
                  <SelectItem value="bi-weekly">Bi-weekly</SelectItem>
                  <SelectItem value="monthly">Monthly</SelectItem>
                  <SelectItem value="quarterly">Quarterly</SelectItem>
                  <SelectItem value="annually">Annually</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="title" className={styles.formLabel}>
              Title
            </label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="amount" className={styles.formLabel}>
              Amount
            </label>
            <div className={styles.amountInputWrapper}>
              <span
                className={`${styles.currencySymbol} font-mono text-lg ${
                  isIncome ? "text-credit" : "text-debit"
                }`}
              >
                $
              </span>
              <Input
                id="amount"
                type="number"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className={`${styles.amountInput} ledger-figures h-12 text-xl ${
                  isIncome ? "text-credit" : "text-debit"
                }`}
                required
              />
            </div>
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="date" className={styles.formLabel}>
              Date
            </label>
            <Input
              id="date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="account" className={styles.formLabel}>
              Account
            </label>
            <Select
              value={selectedAccount}
              onValueChange={setSelectedAccount}
              required
            >
              <SelectTrigger>
                <SelectValue placeholder="Select an account" />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((account) => (
                  <SelectItem key={account.id} value={account.id.toString()}>
                    {account.name} (${account.balance.toFixed(2)})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="category" className={styles.formLabel}>
              Category
            </label>
            <Select value={category} onValueChange={setCategory} required>
              <SelectTrigger>
                <SelectValue placeholder="Select a category" />
              </SelectTrigger>
              <SelectContent>
                {CATEGORIES.map((cat) => (
                  <SelectItem key={cat} value={cat}>
                    {cat}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            type="submit"
            className={styles.submitButton}
            disabled={
              scanning ||
              !title.trim() ||
              !amount ||
              !category ||
              !selectedAccount
            }
          >
            Add Transaction
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
