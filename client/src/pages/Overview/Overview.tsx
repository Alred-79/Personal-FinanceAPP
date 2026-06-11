import styles from "./Overview.module.css";
import { useEffect } from "react";
import { useStore } from "@/store/store";
import PageHeader from "@/components/layout/PageHeader";
import ExpensesCard from "@/components/custom/Overview/ExpensesCard";
import SpendCard from "@/components/custom/Overview/SpendCard";
import TransactionsCard from "@/components/custom/Overview/TransactionsCard";
import TimelineCard from "@/components/custom/Overview/TimelineCard";
import NetWorthCard from "@/components/custom/Overview/NetWorthCard";

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
        description="Your spending, balances, and trends at a glance."
      />
      <div className={styles.overview}>
        <ExpensesCard />
        <SpendCard />
        <TransactionsCard />
        <TimelineCard />
        <NetWorthCard />
      </div>
    </>
  );
}

export default Overview;
