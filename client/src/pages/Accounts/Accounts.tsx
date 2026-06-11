import { useEffect } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Trash2 } from "lucide-react";
import {
  LineChart,
  Line,
  ResponsiveContainer,
  CartesianGrid,
  Tooltip,
  XAxis,
} from "recharts";
import { AccountDialog } from "@/components/custom/AccountDialog/AccountDialog";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { chartColors } from "@/lib/colors";
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

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Your linked and manual accounts."
        actions={<AccountDialog onAccountCreated={handleAccountCreated} />}
      />

      {isLoading && accounts.length === 0 ? (
        <div className="flex h-64 items-center justify-center text-muted-foreground">
          Loading accounts...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {accounts.map((account) => (
            <Card
              key={account.id}
              className="group relative transition-shadow hover:shadow-lg"
            >
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-2 top-2 z-10 opacity-0 transition-opacity group-hover:opacity-100"
                onClick={() => deleteAccount(account.id)}
              >
                <Trash2 className="text-destructive" />
              </Button>
              <div className="flex flex-col gap-4 md:flex-row">
                <div className="flex flex-1 flex-col">
                  <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
                    <h2 className="text-2xl font-bold">{account.name}</h2>
                    <Badge className="rounded-full">{account.type}</Badge>
                  </CardHeader>
                  <CardContent>
                    <div className={`text-3xl font-bold ${account.balance < 0 ? "text-destructive" : "text-success"}`}>
                      {account.balance < 0 ? "-$" : "$"}
                      {Math.abs(account.balance).toLocaleString("en-US", {
                        minimumFractionDigits: 2,
                      })}
                    </div>
                    <div className="mt-4 text-base text-muted-foreground">
                      Last updated:{" "}
                      {new Date(account.last_updated).toLocaleDateString()}
                    </div>
                  </CardContent>
                </div>
                <div className="h-[175px] w-full md:w-[300px]">
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
                        strokeDasharray="3 3"
                        stroke={chartColors.track}
                      />
                      <XAxis
                        dataKey="name"
                        tick={{ fontSize: 12 }}
                        interval="preserveStartEnd"
                      />
                      <Tooltip content={<CustomTooltip />} />
                      <Line
                        type="natural"
                        dataKey="value"
                        stroke={chartColors.primary}
                        dot={false}
                        activeDot={{ r: 4, fill: chartColors.primary }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </Card>
          ))}
          {accounts.length === 0 && (
            <div className="col-span-full flex min-h-[40vh] items-center justify-center text-xl text-muted-foreground">
              You don't seem to have any accounts...
            </div>
          )}
        </div>
      )}
    </>
  );
}
