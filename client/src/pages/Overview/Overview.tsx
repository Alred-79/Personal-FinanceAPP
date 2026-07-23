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
import { DailySurface } from "@/components/custom/DailySurface/DailySurface";
import { SagaChapter } from "@/components/custom/SagaChapter/SagaChapter";
import { FreelancerLeadStrip } from "@/components/custom/Overview/FreelancerLeadStrip";
import { SelfEmployedFork } from "@/components/custom/Onboarding/SelfEmployedFork";

const today = new Date().toLocaleDateString("en-US", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

function Overview() {
  const {
    fetchInitialData,
    fetchTransactionsAndExpenses,
    fetchRecentTransactions,
    fetchNetWorth,
    fetchBudgets,
  } = useStore();

  useEffect(() => {
    fetchInitialData();
    fetchTransactionsAndExpenses();
    fetchRecentTransactions();
    // The Net Worth plates (trend + certificate) and the Budget Status card read
    // store.netWorth / store.budgets, which are otherwise only loaded on the
    // Almanac / Budgets pages — fetch them here so the dashboard isn't empty.
    fetchNetWorth();
    fetchBudgets();
  }, [
    fetchInitialData,
    fetchTransactionsAndExpenses,
    fetchRecentTransactions,
    fetchNetWorth,
    fetchBudgets,
  ]);

  return (
    <>
      <PageHeader
        title="Overview"
        description="Your standing as of the close of business."
        reference={`Form 1040-A · ${today}`}
      />

      {/* The first useful loop: answer, evidence, action. */}
      <div className="mb-6 animate-rise-in">
        <SpendCard />
      </div>
      <div className="mb-6 animate-rise-in delay-1">
        <ForecastCard />
      </div>

      {/* Recent records and spending context follow the decision loop. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:row-span-2 [&>*]:h-full animate-rise-in delay-1">
          <TransactionsCard />
        </div>
        <div className="lg:col-span-2 animate-rise-in delay-2">
          <ExpensesCard />
        </div>
      </div>

      <SelfEmployedFork />

      {/* Account, goal, and trend context. */}
      <div className="mt-6">
        <NetWorthNote />
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="animate-rise-in delay-5">
          <NetWorthCard />
        </div>
        <div className="animate-rise-in delay-6">
          <TimelineCard />
        </div>
      </div>

      {/* Optional work-money and game narrative stay available below core tasks. */}
      <div className="mt-6">
        <FreelancerLeadStrip />
      </div>
      <div className="mt-6">
        <DailySurface />
      </div>
      <div className="mt-6">
        <SagaChapter />
      </div>
    </>
  );
}

export default Overview;
