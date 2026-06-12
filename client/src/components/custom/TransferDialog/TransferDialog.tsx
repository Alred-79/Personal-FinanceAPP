import { useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ArrowRightLeft } from "lucide-react";
import api from "@/lib/api";
import { useStore } from "@/store/store";

/**
 * Intra-app transfer between manually-managed accounts (v2). Plaid-synced
 * accounts are refused by the server (the next sync would overwrite the
 * balance); the error detail is surfaced as-is.
 */
export function TransferDialog() {
  const [open, setOpen] = useState(false);
  const [fromId, setFromId] = useState<string>();
  const [toId, setToId] = useState<string>();
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const { accounts } = useStore();
  const refreshAccounts = useStore((s) => s.fetchAccounts);

  const reset = () => {
    setFromId(undefined);
    setToId(undefined);
    setAmount("");
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fromId || !toId || !amount) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/accounts/transfer/", {
        from_account_id: Number(fromId),
        to_account_id: Number(toId),
        amount: Number(amount),
      });
      useStore.setState({ accountsLoaded: false });
      await refreshAccounts();
      setOpen(false);
      reset();
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? "Transfer failed.";
      setError(detail);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">
          <ArrowRightLeft className="mr-2 h-4 w-4" />
          Transfer
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Transfer Between Accounts</DialogTitle>
          <DialogDescription>
            Moves money between two manually-managed accounts. Bank-synced
            accounts can't be edited — their balance belongs to the bank.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="transfer-from">From</Label>
            <Select value={fromId} onValueChange={setFromId}>
              <SelectTrigger id="transfer-from">
                <SelectValue placeholder="Source account" />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>
                    {a.name} (${a.balance.toFixed(2)})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="transfer-to">To</Label>
            <Select value={toId} onValueChange={setToId}>
              <SelectTrigger id="transfer-to">
                <SelectValue placeholder="Destination account" />
              </SelectTrigger>
              <SelectContent>
                {accounts
                  .filter((a) => String(a.id) !== fromId)
                  .map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      {a.name} (${a.balance.toFixed(2)})
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="transfer-amount">Amount</Label>
            <Input
              id="transfer-amount"
              type="number"
              min="0.01"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
          </div>
          {error && (
            <p className="font-sans text-xs text-debit" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || !fromId || !toId || !amount}
            >
              {submitting ? "Transferring…" : "Transfer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
