import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TransactionDialog } from "@/components/custom/TransactionDialog/TransactionDialog";
import { ScanReceiptButton } from "@/components/custom/ScanReceiptButton/ScanReceiptButton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from "@radix-ui/react-icons";
import { format } from "date-fns";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { categoryColor } from "@/lib/format";
import type { ProjectedTransaction } from "@/store/store";
import { Transaction, Frequency, ReceiptDraft } from "@/types";
import TransactionItem from "@/components/custom/TransactionItem/TransactionItem";
import SpendingInsights from "@/components/custom/SpendingInsights/SpendingInsights";
import { useInstanceCapabilities } from "@/hooks/useInstanceCapabilities";

const PAGE_SIZE = 20;

export default function Transactions() {
  const [searchInput, setSearchInput] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [dateRange, setDateRange] = useState<{
    from: Date | undefined;
    to: Date | undefined;
  }>({ from: undefined, to: undefined });
  const [page, setPage] = useState(1);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<ReceiptDraft | null>(null);
  const capabilities = useInstanceCapabilities();

  const openDialogWith = (draft: ReceiptDraft) => {
    setPendingDraft(draft);
    setDialogOpen(true);
  };

  // Debounce search input
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSearchChange = (value: string) => {
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearchQuery(value);
      setPage(1);
    }, 350);
  };

  const {
    transactions,
    transactionTotal,
    transactionRefreshKey,
    accounts,
    selectedAccountId,
    isLoading,
    accountsLoaded,
    projectedTransactions,
    projectedLoaded,
    fetchAccounts,
    fetchAccountTransactions,
    fetchProjectedTransactions,
    addTransaction,
    deleteTransaction,
    setSelectedAccountId,
    addTxnRequested,
    consumeAddTransaction,
  } = useStore();

  // Reset to page 1 when account changes
  useEffect(() => {
    setPage(1);
  }, [selectedAccountId]);

  // The Command Deck's "add transaction" action navigates here and raises a
  // consume-once flag; open the dialog and clear it so a later visit doesn't.
  useEffect(() => {
    if (addTxnRequested) {
      setPendingDraft(null);
      setDialogOpen(true);
      consumeAddTransaction();
    }
  }, [addTxnRequested, consumeAddTransaction]);

  // Fetch when filters/page/account/refresh change
  useEffect(() => {
    const params: Record<string, unknown> = { page, page_size: PAGE_SIZE };
    if (searchQuery) params.q = searchQuery;
    if (dateRange.from) params.date_from = format(dateRange.from, "yyyy-MM-dd");
    if (dateRange.to) params.date_to = format(dateRange.to, "yyyy-MM-dd");
    fetchAccountTransactions(selectedAccountId, params);
  }, [searchQuery, dateRange, page, selectedAccountId, transactionRefreshKey, fetchAccountTransactions]);

  useEffect(() => {
    const loadStatic = async () => {
      if (!accountsLoaded) await fetchAccounts();
      if (!projectedLoaded) await fetchProjectedTransactions();
    };
    loadStatic();
  }, [accountsLoaded, projectedLoaded, fetchAccounts, fetchProjectedTransactions]);

  const categorizeTransactions = useCallback((txs: Transaction[]) => {
    const now = new Date();
    const threeDaysAgo = new Date(now);
    threeDaysAgo.setDate(now.getDate() - 3);
    return {
      recent: txs.filter((t) => {
        const d = new Date(t.date);
        return d <= now && d >= threeDaysAgo;
      }),
      past: txs.filter((t) => new Date(t.date) < threeDaysAgo),
      pending: txs.filter((t) => new Date(t.date) > now),
    };
  }, []);

  const filteredProjected = useMemo((): Transaction[] => {
    const query = searchQuery.toLowerCase();
    return projectedTransactions
      .filter((p: ProjectedTransaction) =>
        selectedAccountId !== "all"
          ? p.account_id.toString() === selectedAccountId
          : true
      )
      .filter((p) => {
        if (!searchQuery) return true;
        return (
          p.title.toLowerCase().includes(query) ||
          p.category.toLowerCase().includes(query) ||
          p.amount.toString().includes(query) ||
          p.date.includes(query)
        );
      })
      .filter((p) => {
        if (!dateRange.from && !dateRange.to) return true;
        const d = new Date(p.date);
        const afterFrom = !dateRange.from || d >= dateRange.from;
        const beforeTo = !dateRange.to || d <= dateRange.to;
        return afterFrom && beforeTo;
      })
      .map((p) => ({
        id: p.source_id,
        title: p.title,
        amount: p.amount,
        date: p.date,
        category: p.category,
        type: "expense" as const,
        backgroundColor: categoryColor(p.category),
      }));
  }, [projectedTransactions, selectedAccountId, searchQuery, dateRange]);

  const renderProjected = () => {
    const projected = filteredProjected;
    if (projected.length === 0) return null;
    return (
      <>
        <p
          className="mb-1 mt-4 font-sans text-[10px] uppercase tracking-[0.18em] text-gold"
          title="Predicted future charges based on your recurring spending patterns."
        >
          ❦ Expected · recurring
        </p>
        {projected.map((t, i) => (
          <TransactionItem
            key={`projected-${t.id}-${t.date}-${i}`}
            transaction={t}
            onDelete={null}
            style={{ opacity: 0.55 }}
          />
        ))}
      </>
    );
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

  const handleDeleteTransaction = async (transaction: Transaction) => {
    await deleteTransaction(transaction.id, transaction.type);
  };

  const columns: {
    key: "recent" | "past" | "pending";
    title: string;
    subtitle: string;
  }[] = [
    { key: "recent", title: "Recent", subtitle: "Last 3 days" },
    { key: "past", title: "Past", subtitle: "Older than 3 days" },
    {
      key: "pending",
      title: "Pending",
      subtitle: "Future dates & expected recurring",
    },
  ];

  const grouped = categorizeTransactions(transactions);
  const totalPages = Math.max(1, Math.ceil(transactionTotal / PAGE_SIZE));

  const resetDateRange = () => {
    setDateRange({ from: undefined, to: undefined });
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="The Ledger"
        description="Every posting, ruled and reconciled."
        reference="Folio III · General Journal"
        actions={
          <div className="flex items-center gap-2">
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
        }
      />

      {/* Spending insights (v2 analytics pivot) */}
      <SpendingInsights />

      {/* Filters */}
      <Card className="mb-6">
        <CardContent className="flex flex-col gap-4 pt-6 md:flex-row md:flex-wrap md:items-end">
          <div className="flex flex-col gap-2">
            <Label>Search</Label>
            <Input
              type="text"
              placeholder="Title or category..."
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full md:w-[280px]"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label>Account</Label>
            <Select
              value={selectedAccountId}
              onValueChange={(v) => {
                setSelectedAccountId(v);
              }}
            >
              <SelectTrigger className="w-full md:w-[200px]">
                <SelectValue placeholder="Select an account" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Accounts</SelectItem>
                {accounts.map((account) => (
                  <SelectItem key={account.id} value={account.id.toString()}>
                    {account.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Date range</Label>
            <div className="flex flex-wrap gap-2">
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    className="w-[150px] justify-start text-left font-normal"
                  >
                    <CalendarIcon className="mr-2 h-4 w-4" />
                    {dateRange.from ? (
                      format(dateRange.from, "MM/dd/yyyy")
                    ) : (
                      <span>From date</span>
                    )}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={dateRange.from}
                    onSelect={(date) => {
                      setDateRange((prev) => ({ ...prev, from: date }));
                      setPage(1);
                    }}
                    initialFocus
                  />
                </PopoverContent>
              </Popover>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    className="w-[150px] justify-start text-left font-normal"
                  >
                    <CalendarIcon className="mr-2 h-4 w-4" />
                    {dateRange.to ? (
                      format(dateRange.to, "MM/dd/yyyy")
                    ) : (
                      <span>To date</span>
                    )}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={dateRange.to}
                    onSelect={(date) => {
                      setDateRange((prev) => ({ ...prev, to: date }));
                      setPage(1);
                    }}
                    initialFocus
                  />
                </PopoverContent>
              </Popover>
              <Button variant="outline" onClick={resetDateRange}>
                Reset
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Columns — three ruled ledger pages */}
      {isLoading && transactions.length === 0 ? (
        <div className="flex h-64 items-center justify-center font-sans italic text-muted-foreground">
          Ruling the ledger…
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {columns.map(({ key, title, subtitle }) => {
            const items = grouped[key];
            const showProjected = key === "pending";
            const isEmpty =
              items.length === 0 &&
              (!showProjected || filteredProjected.length === 0);
            return (
              <Card key={key} className="flex flex-col">
                <CardHeader className="pb-2">
                  <div className="flex items-baseline justify-between">
                    <CardTitle>{title}</CardTitle>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {items.length}
                    </span>
                  </div>
                  <p className="font-sans text-[11px] italic text-muted-foreground">
                    {subtitle}
                  </p>
                </CardHeader>
                <CardContent className="flex-1 px-3">
                  {/* Column ruling */}
                  <div className="grid grid-cols-[1fr_auto] border-b border-rule-strong/40 px-2.5 pb-1 font-sans text-[9px] uppercase tracking-[0.16em] text-muted-foreground">
                    <span>Entry</span>
                    <span>Amount</span>
                  </div>
                  <div className="max-h-[58vh] overflow-y-auto">
                    {isEmpty ? (
                      <div className="flex flex-col items-center gap-1.5 py-14 text-center">
                        <span className="text-2xl text-rule-strong/50" aria-hidden>
                          ☞
                        </span>
                        <p className="font-display text-lg text-muted-foreground">
                          No entries on this page of the ledger
                        </p>
                        <p className="font-sans text-xs italic text-muted-foreground">
                          Record a transaction or adjust the filters above.
                        </p>
                      </div>
                    ) : (
                      items.map((transaction) => (
                        <TransactionItem
                          key={`${transaction.id}-${transaction.type}`}
                          transaction={transaction}
                          onDelete={() => handleDeleteTransaction(transaction)}
                        />
                      ))
                    )}
                    {showProjected && renderProjected()}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      <div className="mt-6 flex items-center justify-between border-t border-rule-strong/30 pt-4 font-mono text-xs text-muted-foreground">
        <span>
          {transactionTotal > 0
            ? `Entries ${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, transactionTotal)} of ${transactionTotal}`
            : "No entries on file"}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || isLoading}
          >
            <ChevronLeftIcon className="h-4 w-4" />
            Prev
          </Button>
          <span className="px-1 tabular-nums">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || isLoading}
          >
            Next
            <ChevronRightIcon className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </>
  );
}
