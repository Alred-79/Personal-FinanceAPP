import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useStore } from "@/store/store";
import TransactionItem from "@/components/custom/TransactionItem/TransactionItem";
import { TransactionDialog } from "@/components/custom/TransactionDialog/TransactionDialog";
import { ScanReceiptButton } from "@/components/custom/ScanReceiptButton/ScanReceiptButton";
import { Transaction, Frequency, ReceiptDraft } from "@/types";
import { useState } from "react";
import { useInstanceCapabilities } from "@/hooks/useInstanceCapabilities";

function TransactionsCard() {
  const { recentTransactions, addTransaction, deleteTransaction } = useStore();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<ReceiptDraft | null>(null);
  const capabilities = useInstanceCapabilities();

  const openDialogWith = (draft: ReceiptDraft) => {
    setPendingDraft(draft);
    setDialogOpen(true);
  };

  const handleNewTransaction = async (transaction: {
    title: string;
    amount: number;
    date: string;
    category: string;
    isIncome: boolean;
    account_id: number;
    recurrence?: Frequency;
  }) => {
    await addTransaction(transaction);
  };

  const handleDelete = async (transaction: Transaction) => {
    await deleteTransaction(transaction.id, transaction.type);
  };

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle>Recent Postings</CardTitle>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Folio III
        </span>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">
        <div className="-mx-1 flex-1 overflow-y-auto pr-1" style={{ maxHeight: "30rem" }}>
          {recentTransactions.length === 0 ? (
            <p className="py-8 text-center font-sans text-sm italic text-muted-foreground">
              No entries posted yet.
            </p>
          ) : (
            recentTransactions.map((transaction) => (
              <TransactionItem
                key={`${transaction.id}-${transaction.type}`}
                transaction={transaction}
                onDelete={() => handleDelete(transaction)}
              />
            ))
          )}
        </div>
        <div className="mt-4 flex flex-col gap-2 border-t border-rule-strong/30 pt-4 [&>button]:w-full">
          {capabilities?.unstructured_import && (
            <ScanReceiptButton onScanned={openDialogWith} />
          )}
          <TransactionDialog
            onSubmit={handleNewTransaction}
            open={dialogOpen}
            onOpenChange={(o) => {
              setDialogOpen(o);
              if (!o) setPendingDraft(null);
            }}
            initialDraft={pendingDraft}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export default TransactionsCard;
