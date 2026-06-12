import { useEffect } from "react";
import { useStore } from "@/store/store";
import PageHeader from "@/components/layout/PageHeader";
import NetWorthNote from "@/components/custom/Overview/NetWorthNote";
import ExpensesCard from "@/components/custom/Overview/ExpensesCard";
import SpendCard from "@/components/custom/Overview/SpendCard";
import TransactionsCard from "@/components/custom/Overview/TransactionsCard";
import TimelineCard from "@/components/custom/Overview/TimelineCard";
import NetWorthCard from "@/components/custom/Overview/NetWorthCard";
import ForecastCard from "@/components/custom/Overview/ForecastCard";
import { SafeToSpend } from "@/components/custom/SafeToSpend/SafeToSpend";
import { DailySurface } from "@/components/custom/DailySurface/DailySurface";
import { SagaChapter } from "@/components/custom/SagaChapter/SagaChapter";

const today = new Date().toLocaleDateString("en-US", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

function Overview() {
  const { fetchInitialData, fetchTransactionsAndExpenses, fetchRecentTransactions } =
    useStore();

  useEffect(() => {
    fetchInitialData();
    fetchTransactionsAndExpenses();
    fetchRecentTransactions();
  }, [fetchInitialData, fetchTransactionsAndExpenses, fetchRecentTransactions]);

  return (
    <>
      <PageHeader
        title="Overview"
        description="Your standing as of the close of business."
        reference={`Form 1040-A · ${today}`}
      />

      {/* The glanceable hero: ONE number, identical across modes (v4 §5.2).
          Sits above the net-worth note so it's the first thing the eye lands on. */}
      <div className="mb-6 animate-rise-in">
        <SafeToSpend />
      </div>

      {/* The daily surface: today's one verb + collect (hidden in off mode).
          NEVER more than those two elements. The Expedition home (08) will
          replace this card as the daily surface. */}
      <div className="mb-6">
        <DailySurface />
      </div>

      {/* The weekly saga chapter (Sunday; hidden in off). Ends in one action. */}
      <div className="mb-6">
        <SagaChapter />
      </div>

      {/* The banknote hero */}
      <div className="mb-6">
        <NetWorthNote />
      </div>

      {/* Document body: a deliberate two-column ledger spread */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left rail: the running ledger, spanning the full height */}
        <div className="lg:row-span-2 [&>*]:h-full animate-rise-in delay-1">
          <TransactionsCard />
        </div>

        {/* Right two-thirds: the analytical plates */}
        <div className="grid grid-cols-1 gap-6 lg:col-span-2 sm:grid-cols-2">
          <div className="animate-rise-in delay-2">
            <SpendCard />
          </div>
          <div className="animate-rise-in delay-3">
            <ExpensesCard />
          </div>
        </div>

        <div className="lg:col-span-2 animate-rise-in delay-4">
          <ForecastCard />
        </div>
      </div>

      {/* Lower spread: trend plates */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="animate-rise-in delay-5">
          <NetWorthCard />
        </div>
        <div className="animate-rise-in delay-6">
          <TimelineCard />
        </div>
      </div>
    </>
  );
}

export default Overview;
