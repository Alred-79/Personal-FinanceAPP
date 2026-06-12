import { useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Trash2, Landmark } from "lucide-react";
import {
  LineChart,
  Line,
  ResponsiveContainer,
  CartesianGrid,
  Tooltip,
  XAxis,
} from "recharts";
import { AccountDialog } from "@/components/custom/AccountDialog/AccountDialog";
import { TransferDialog } from "@/components/custom/TransferDialog/TransferDialog";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { ink } from "@/lib/chart";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import CustomTooltip from "@/components/custom/Tooltip/Tooltip";

export default function Accounts() {
  const { accounts, isLoading, fetchAccounts, addAccount, deleteAccount } =
    useStore();

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  const handleAccountCreated = async (account: {
    name: string;
    type: string;
    balance: number;
  }) => {
    await addAccount(account);
  };

  const total = accounts.reduce((sum, a) => sum + a.balance, 0);

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Every passbook held in your name."
        reference="Folio II · Register of Holdings"
        actions={
          <div className="flex items-center gap-2">
            <TransferDialog />
            <AccountDialog onAccountCreated={handleAccountCreated} />
          </div>
        }
      />

      {accounts.length > 0 && (
        <div className="mb-6 flex flex-wrap items-baseline justify-between gap-2 border-b border-rule-strong/30 pb-4">
          <p className="dept-label">Aggregate holdings</p>
          <p className="intaglio text-3xl text-foreground">
            <AnimatedNumber value={total} />
          </p>
        </div>
      )}

      {isLoading && accounts.length === 0 ? (
        <div className="flex h-64 items-center justify-center font-sans italic text-muted-foreground">
          Pulling the passbooks…
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {accounts.map((account, i) => (
            <Card
              key={account.id}
              className="group relative animate-rise-in"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <button
                aria-label="Delete account"
                className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center text-muted-foreground opacity-0 transition-opacity hover:text-debit group-hover:opacity-100"
                onClick={() => deleteAccount(account.id)}
              >
                <Trash2 size={17} />
              </button>
              <div className="flex flex-col gap-4 md:flex-row">
                <div className="flex flex-1 flex-col p-6">
                  <div className="mb-4 flex items-center gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center border border-rule-strong/40 bg-card text-gold">
                      <Landmark className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <h2 className="font-display text-xl font-semibold leading-tight">
                        {account.name}
                      </h2>
                      <Badge variant="outline" className="mt-1">
                        {account.type}
                      </Badge>
                    </div>
                  </div>

                  <p
                    className={`intaglio text-3xl ${
                      account.balance < 0 ? "ink-debit" : "text-foreground"
                    }`}
                  >
                    {account.balance < 0 ? "−" : ""}
                    {formatCurrency(Math.abs(account.balance))}
                  </p>
                  <p className="mt-3 font-mono text-[11px] text-muted-foreground">
                    Reconciled {new Date(account.last_updated).toLocaleDateString()}
                  </p>
                </div>

                <div className="h-[175px] w-full self-center md:w-[300px] md:pr-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={
                        account.transactions
                          ?.sort(
                            (a, b) =>
                              new Date(a.date).getTime() -
                              new Date(b.date).getTime()
                          )
                          .reduce(
                            (
                              acc: { name: string; value: number }[],
                              transaction,
                              _,
                              transactions
                            ) => {
                              const date = new Date(transaction.date);
                              const monthYear = date.toLocaleString("default", {
                                month: "short",
                                year: "numeric",
                              });

                              const currentBalance =
                                account.balance -
                                transactions
                                  .filter((t) => new Date(t.date) > date)
                                  .reduce(
                                    (sum, t) =>
                                      sum +
                                      (t.type === "income"
                                        ? t.amount
                                        : -t.amount),
                                    0
                                  );

                              const existingEntry = acc.find(
                                (entry) => entry.name === monthYear
                              );
                              if (existingEntry) {
                                existingEntry.value = currentBalance;
                              } else {
                                acc.push({ name: monthYear, value: currentBalance });
                              }
                              return acc;
                            },
                            []
                          ) || []
                      }
                    >
                      <CartesianGrid
                        vertical
                        strokeDasharray="2 4"
                        stroke={ink("--rule", 0.6)}
                      />
                      <XAxis
                        dataKey="name"
                        tick={{
                          fontSize: 10,
                          fontFamily: "'Spline Sans Mono', monospace",
                          fill: ink("--muted-foreground"),
                        }}
                        interval="preserveStartEnd"
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip content={<CustomTooltip />} />
                      <Line
                        type="natural"
                        dataKey="value"
                        stroke={ink("--credit")}
                        strokeWidth={1.6}
                        dot={false}
                        activeDot={{ r: 4, fill: ink("--credit") }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </Card>
          ))}
          {accounts.length === 0 && (
            <div className="col-span-full flex min-h-[40vh] flex-col items-center justify-center gap-3">
              <p className="font-display text-2xl text-muted-foreground">
                No accounts on the register
              </p>
              <p className="font-sans text-sm italic text-muted-foreground">
                Add a passbook or link a bank to begin.
              </p>
            </div>
          )}
        </div>
      )}
    </>
  );
}
