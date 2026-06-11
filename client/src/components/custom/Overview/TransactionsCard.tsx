import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import styles from "./styles.module.css";
import { useStore } from "@/store/store";
import TransactionItem from "@/components/custom/TransactionItem/TransactionItem";
import { TransactionDialog } from "@/components/custom/TransactionDialog/TransactionDialog";
import { ScanReceiptButton } from "@/components/custom/ScanReceiptButton/ScanReceiptButton";
import { Transaction, Frequency, ReceiptDraft } from "@/types";
import { useIsMobile } from "@/hooks/responsive";
import { useState } from "react";

function TransactionsCard() {
  const { recentTransactions, addTransaction, deleteTransaction } = useStore();
  const isMobile = useIsMobile();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<ReceiptDraft | null>(null);

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
    <Card className={styles.spanTwoRows}>
      <CardHeader>
        <CardTitle
          className={styles.cardTitle}
          style={isMobile ? { textAlign: "center" } : {}}
        >
          Recent Transactions
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className={styles.transactionsContainer}
          style={{ padding: recentTransactions.length > 0 ? "1rem" : "0" }}
        >
          {recentTransactions.length === 0 ? (
            <p className="font-mono text-sm text-muted-foreground py-4 text-center">
              No recent transactions yet.
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
        <div className="new-transaction flex items-center gap-2">
          <ScanReceiptButton onScanned={openDialogWith} />
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
