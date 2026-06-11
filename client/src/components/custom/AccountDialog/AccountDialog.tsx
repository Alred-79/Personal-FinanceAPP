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
import { Plus } from "lucide-react";
import styles from "./AccountDialog.module.css";

interface AccountDialogProps {
  onAccountCreated: (account: {
    name: string;
    type: string;
    balance: number;
  }) => Promise<void>;
}

export function AccountDialog({ onAccountCreated }: AccountDialogProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [otherType, setOtherType] = useState("");
  const [balance, setBalance] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!type) {
      setError("Please select an account type");
      return;
    }

    if (type === "other" && !otherType) {
      setError("Please specify the account type");
      return;
    }

    try {
      const finalType = type === "other" ? otherType : type;
      await onAccountCreated({
        name,
        type: finalType,
        balance: parseFloat(balance),
      });

      // Reset form and close dialog
      setName("");
      setType("");
      setOtherType("");
      setBalance("");
      setError("");
      setOpen(false);
    } catch (error) {
      console.error("Error creating account:", error);
      setError("Failed to create account. Please try again.");
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          New Account
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create New Account</DialogTitle>
          <DialogDescription>
            Add a new account to track your finances.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Account Name</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="type">Account Type</Label>
            <Select
              value={type}
              onValueChange={(value) => {
                setType(value);
                setError("");
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select account type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="spending">Spending</SelectItem>
                <SelectItem value="checking">Checking</SelectItem>
                <SelectItem value="savings">Savings</SelectItem>
                <SelectItem value="credit">Credit</SelectItem>
                <SelectItem value="investment">Investment</SelectItem>
                <SelectItem value="other">Other</SelectItem>
              </SelectContent>
            </Select>
            {type === "other" && (
              <div className="mt-2">
                <Input
                  placeholder="Specify account type"
                  value={otherType}
                  onChange={(e) => {
                    setOtherType(e.target.value);
                    setError("");
                  }}
                />
              </div>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="balance">Initial Balance</Label>
            <div className="relative">
              <span className="absolute left-2 top-1/2 transform -translate-y-1/2">
                $
              </span>
              <Input
                id="balance"
                type="number"
                step="0.01"
                value={balance}
                onChange={(e) => setBalance(e.target.value)}
                className={styles["balance-input"]}
                required
              />
            </div>
          </div>
          {error && <div className="text-destructive text-sm mt-2">{error}</div>}
          <DialogFooter>
            <Button type="submit" className="w-full">
              Create Account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
