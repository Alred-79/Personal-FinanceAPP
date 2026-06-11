import { create } from "zustand";
import {
  Transaction,
  Expense,
  Notification,
  Subscription,
  Account,
  Frequency,
  ReceiptDraft,
} from "../types";
import api from "../lib/api";
import { currentWeekRange } from "../lib/dates";

export type { Account };

export interface User {
  id: number;
  username: string;
  full_name: string | null;
}

interface BackendGoal {
  id: number;
  name: string;
  description: string;
  amount: number;
  progress: number;
  date: string;
  completed: boolean;
}

export interface Goal {
  id?: number;
  name: string;
  description: string;
  amount: number;
  progress?: number;
  deadline: Date;
  completed?: boolean;
  date?: string;
}

export interface Budget {
  id: number;
  category: string;
  monthly_limit: number;
  effective_limit: number;
  rollover: boolean;
  spent: number;
  remaining: number;
  prorated_target: number;
  over_budget: boolean;
  on_pace: boolean;
}

export interface NetWorthPoint {
  date: string;
  total: number;
}

export interface ProjectedTransaction {
  id: number;
  source_id: number;
  title: string;
  amount: number;
  date: string;
  category: string;
  recurrence: string;
  account_id: number;
  type: "expense";
  projected: true;
}

import { categoryColor } from "../lib/format";

interface StoreState {
  transactions: Transaction[];
  recentTransactions: Transaction[];
  expenses: Expense[];
  budgetAllotment: number;
  spendOverTime: number;
  fixedPerMonth: number;
  warningPosition: number;
  savingsPercent: number;
  isLoading: boolean;
  hasLoaded: boolean;
  accounts: Account[];
  accountsLoaded: boolean;
  selectedAccountId: string;
  transactionsLoaded: boolean;
  transactionTotal: number;
  transactionRefreshKey: number;
  goals: Goal[];
  goalsLoaded: boolean;
  user: User | null;
  userLoaded: boolean;
  linkToken: string | null;
  isLoggedIn: boolean;
  settingsLoaded: boolean;
  budgets: Budget[];
  budgetsLoaded: boolean;
  netWorth: NetWorthPoint[];
  netWorthLoaded: boolean;
  projectedTransactions: ProjectedTransaction[];
  projectedLoaded: boolean;
  notifications: Notification[];
  unreadCount: number;
  notificationsLoaded: boolean;
  subscriptions: Subscription[];
  subscriptionsLoaded: boolean;

  // Actions
  fetchInitialData: () => Promise<void>;
  fetchTransactionsAndExpenses: () => Promise<void>;
  fetchRecentTransactions: () => Promise<void>;
  fetchAccounts: () => Promise<void>;
  fetchAccountTransactions: (
    accountId: string,
    params?: {
      q?: string;
      category?: string;
      date_from?: string;
      date_to?: string;
      amount_min?: number;
      amount_max?: number;
      page?: number;
      page_size?: number;
    }
  ) => Promise<void>;
  addAccount: (account: {
    name: string;
    type: string;
    balance: number;
  }) => Promise<void>;
  addTransaction: (transaction: {
    title: string;
    amount: number;
    date: string;
    category: string;
    isIncome: boolean;
    account_id?: number;
    frequency?: Frequency;
  }) => Promise<void>;
  scanReceipt: (file: File) => Promise<ReceiptDraft>;
  deleteTransaction: (
    transactionId: number,
    type: "income" | "expense"
  ) => Promise<void>;
  updateWarningPosition: (position: number) => Promise<void>;
  refreshBudgetData: () => Promise<void>;
  setSelectedAccountId: (accountId: string) => void;

  // Goals actions
  fetchGoals: () => Promise<void>;
  addGoal: (goal: Omit<Goal, "id">) => Promise<void>;
  updateGoal: (goal: Goal) => Promise<void>;
  deleteGoal: (goalId: number) => Promise<void>;
  updateGoalProgress: (goalId: number, progress: number) => Promise<void>;

  // New actions for user and Plaid
  fetchUser: () => Promise<void>;
  logout: () => void;
  fetchLinkToken: () => Promise<void>;
  exchangePublicToken: (
    publicToken: string,
    institutionName: string
  ) => Promise<void>;

  // New actions for settings
  updateSavingsPercent: (percent: number) => Promise<void>;
  fetchUserSettings: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;

  // Plaid sync (runs in the background, we don't wait on it)
  syncTransactions: () => Promise<void>;

  deleteAccount: (accountId: number) => Promise<void>;

  // Budgets
  fetchBudgets: () => Promise<void>;
  addBudget: (budget: {
    category: string;
    monthly_limit: number;
    rollover: boolean;
  }) => Promise<void>;
  updateBudget: (
    budgetId: number,
    budget: { category: string; monthly_limit: number; rollover: boolean }
  ) => Promise<void>;
  deleteBudget: (budgetId: number) => Promise<void>;

  // Net worth
  fetchNetWorth: () => Promise<void>;

  // Projected recurring transactions
  fetchProjectedTransactions: () => Promise<void>;

  // Notifications & subscriptions
  fetchNotifications: () => Promise<void>;
  markNotificationRead: (notificationId: number) => Promise<void>;
  markAllNotificationsRead: () => Promise<void>;
  fetchSubscriptions: () => Promise<void>;
}

export const useStore = create<StoreState>((set, get) => ({
  transactions: [],
  recentTransactions: [],
  expenses: [],
  budgetAllotment: 1,
  spendOverTime: 1,
  fixedPerMonth: 0,
  warningPosition: 25,
  savingsPercent: 20,
  isLoading: false,
  hasLoaded: false,
  accounts: [],
  accountsLoaded: false,
  selectedAccountId: "all",
  transactionsLoaded: false,
  transactionTotal: 0,
  transactionRefreshKey: 0,
  goals: [],
  goalsLoaded: false,
  user: null,
  userLoaded: false,
  linkToken: null,
  isLoggedIn: false,
  settingsLoaded: false,
  budgets: [],
  budgetsLoaded: false,
  netWorth: [],
  netWorthLoaded: false,
  projectedTransactions: [],
  projectedLoaded: false,
  notifications: [],
  unreadCount: 0,
  notificationsLoaded: false,
  subscriptions: [],
  subscriptionsLoaded: false,

  setSelectedAccountId: (accountId: string) => {
    set({ selectedAccountId: accountId });
  },

  fetchAccountTransactions: async (accountId: string, params = {}) => {
    try {
      const queryParams: Record<string, unknown> = { ...params };
      if (accountId !== "all") {
        queryParams.account_id = accountId;
      }
      const response = await api.get("/transactions", { params: queryParams });
      const { items, total } = response.data;
      const transactionsWithColors = items.map((t: Transaction) => ({
        ...t,
        backgroundColor: categoryColor(t.category),
      }));
      set({ transactions: transactionsWithColors, transactionTotal: total, transactionsLoaded: true });
    } catch (error) {
      console.error("Error fetching transactions:", error);
    }
  },

  fetchInitialData: async () => {
    if (get().hasLoaded) return;

    try {
      const userResponse = await api.get("/users/me/");
      const userData = await userResponse.data;
      set({ warningPosition: userData.spend_warning });

      const budgetResponse = await api.get("/spend/budget-allotment");
      const budgetData = await budgetResponse.data;
      set({ budgetAllotment: budgetData });

      const fixedResponse = await api.get("/expenses/fixed-per-month");
      const fixedData = await fixedResponse.data;
      set({ fixedPerMonth: fixedData });

      const { startDate, endDate } = currentWeekRange();
      const spendResponse = await api.get(
        `/spend/spend-over-time?start_date=${startDate}&end_date=${endDate}`
      );

      const spendData = await spendResponse.data;
      set({ spendOverTime: spendData, hasLoaded: true });
    } catch (error) {
      console.error("Error fetching initial data:", error);
    }
  },

  fetchTransactionsAndExpenses: async () => {
    try {
      const expensesResponse = await api.get("/expenses");
      set({ expenses: expensesResponse.data });
    } catch (error) {
      console.error("Error fetching expenses:", error);
    }
  },

  fetchRecentTransactions: async () => {
    try {
      const response = await api.get("/transactions", {
        params: { page: 1, page_size: 20 },
      });
      const { items } = response.data;
      set({
        recentTransactions: items.map((t: Transaction) => ({
          ...t,
          backgroundColor:
            categoryColor(t.category),
        })),
      });
    } catch (error) {
      console.error("Error fetching recent transactions:", error);
    }
  },

  fetchAccounts: async () => {
    if (get().accountsLoaded) return;

    try {
      const response = await api.get("/accounts");

      const accountsWithTransactions = await Promise.all(
        response.data.map(async (account: Account) => {
          try {
            const transactionsResponse = await api.get(
              `/accounts/${account.id}/transactions`
            );
            return { ...account, transactions: transactionsResponse.data };
          } catch (error) {
            console.error(
              `Error fetching transactions for account ${account.id}:`,
              error
            );
            return account;
          }
        })
      );

      set({
        accounts: accountsWithTransactions.filter(Boolean),
        accountsLoaded: true,
      });
    } catch (error) {
      console.error("Error fetching accounts:", error);
    }
  },

  addAccount: async (account) => {
    set({ isLoading: true });
    try {
      await api.post("/accounts", account);
      set({ accountsLoaded: false });
      await get().fetchAccounts();
    } catch (error) {
      console.error("Error creating account:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  addTransaction: async (transaction) => {
    set({ isLoading: true });
    try {
      await api.post(
        `/${transaction.isIncome ? "income" : "expenses"}`,
        transaction
      );
      set((s) => ({ transactionRefreshKey: s.transactionRefreshKey + 1 }));
      await get().fetchRecentTransactions();
      await get().refreshBudgetData();
    } catch (error) {
      console.error("Error adding transaction:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  scanReceipt: async (file: File) => {
    // Multipart upload to the vision endpoint. Overriding the Content-Type lets
    // axios set the multipart boundary instead of reusing the JSON default.
    // Errors propagate to the caller so the UI can surface the server `detail`.
    const form = new FormData();
    form.append("file", file);
    const { data } = await api.post("/receipts/scan", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data as ReceiptDraft;
  },

  deleteTransaction: async (
    transactionId: number,
    type: "income" | "expense"
  ) => {
    set({ isLoading: true });
    try {
      const endpoint = type === "income" ? "income" : "expenses";
      await api.delete(`/${endpoint}/${transactionId}`);
      set((s) => ({ transactionRefreshKey: s.transactionRefreshKey + 1 }));
      await get().fetchRecentTransactions();
      await get().refreshBudgetData();
    } catch (error) {
      console.error("Error deleting transaction:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  updateWarningPosition: async (position: number) => {
    set({ isLoading: true });
    try {
      await api.put("/settings/preferences/", {
        spend_warning: position,
      });

      set({ warningPosition: position });
    } catch (error) {
      console.error("Error updating warning position:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  refreshBudgetData: async () => {
    set({ isLoading: true });
    try {
      const budgetResponse = await api.get("/spend/budget-allotment");
      const budgetData = await budgetResponse.data;
      set({ budgetAllotment: budgetData });

      const { startDate, endDate } = currentWeekRange();
      const spendResponse = await api.get(
        `/spend/spend-over-time?start_date=${startDate}&end_date=${endDate}`
      );

      const spendData = await spendResponse.data;
      set({ spendOverTime: spendData });

      const fixedResponse = await api.get("/expenses/fixed-per-month");
      const fixedData = await fixedResponse.data;
      set({ fixedPerMonth: fixedData });
    } catch (error) {
      console.error("Error refreshing budget data:", error);
    } finally {
      set({ isLoading: false });
    }
  },

  fetchGoals: async () => {
    if (get().goalsLoaded) return;

    try {
      const response = await api.get("/goals");

      const goalsWithDates = response.data.map((goal: BackendGoal) => ({
        ...goal,
        deadline: new Date(goal.date),
      }));
      set({ goals: goalsWithDates, goalsLoaded: true });
    } catch (error) {
      console.error("Error fetching goals:", error);
    }
  },

  addGoal: async (goal) => {
    set({ isLoading: true });
    try {
      const formattedGoal = {
        ...goal,
        date: goal.deadline.toISOString().split("T")[0],
        deadline: undefined,
      };

      await api.post("/goals", formattedGoal);
      set({ goalsLoaded: false });
      await get().fetchGoals();
    } catch (error) {
      console.error("Error creating goal:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  updateGoal: async (goal) => {
    set({ isLoading: true });
    try {
      const formattedGoal = {
        ...goal,
        date: goal.deadline.toISOString().split("T")[0],
        deadline: undefined,
      };

      await api.put(`/goals/${goal.id}`, formattedGoal);
      set({ goalsLoaded: false });
      await get().fetchGoals();
    } catch (error) {
      console.error("Error updating goal:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  deleteGoal: async (goalId) => {
    set({ isLoading: true });
    try {
      await api.delete(`/goals/${goalId}`);
      set({ goalsLoaded: false });
      await get().fetchGoals();
    } catch (error) {
      console.error("Error deleting goal:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  updateGoalProgress: async (goalId, progress) => {
    set({ isLoading: true });
    try {
      const goal = get().goals.find((g) => g.id === goalId);
      if (!goal) return;

      const formattedGoal = {
        ...goal,
        progress,
        date: goal.deadline.toISOString().split("T")[0],
        deadline: undefined,
      };

      await api.put(`/goals/${goalId}`, formattedGoal);
      set({ goalsLoaded: false });
      await get().fetchGoals();
    } catch (error) {
      console.error("Error updating goal progress:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  fetchUser: async () => {
    if (get().userLoaded) return;

    try {
      const response = await api.get("/users/me/");
      set({ user: response.data, isLoggedIn: true, userLoaded: true });
    } catch (error) {
      console.error("Error fetching user:", error);
      set({ isLoggedIn: false, user: null, userLoaded: true });
    }
  },

  logout: () => {
    api.post("/logout/").catch(() => {});
    set({
      isLoggedIn: false,
      user: null,
      userLoaded: false,
      linkToken: null,
      hasLoaded: false,
      accountsLoaded: false,
      transactionsLoaded: false,
      goalsLoaded: false,
      settingsLoaded: false,
      budgetsLoaded: false,
      netWorthLoaded: false,
      projectedLoaded: false,
      transactions: [],
      recentTransactions: [],
      expenses: [],
      accounts: [],
      goals: [],
      budgets: [],
      netWorth: [],
      projectedTransactions: [],
      notifications: [],
      unreadCount: 0,
      notificationsLoaded: false,
      subscriptions: [],
      subscriptionsLoaded: false,
    });
  },

  fetchLinkToken: async () => {
    try {
      const user = get().user;
      if (!user) return;

      const response = await api.get(`/plaid/link-token?user_id=${user.id}`);
      set({ linkToken: response.data.link_token });
    } catch (error) {
      console.error("Error fetching link token:", error);
      throw error;
    }
  },

  exchangePublicToken: async (publicToken: string, institutionName: string) => {
    try {
      await api.post("/plaid/exchange-public-token", {
        public_token: publicToken,
        name: institutionName,
      });

      set({ accountsLoaded: false });
      await get().fetchAccounts();
    } catch (error) {
      console.error("Error exchanging public token:", error);
      throw error;
    }
  },

  fetchUserSettings: async () => {
    if (get().settingsLoaded) return;

    try {
      const response = await api.get("/users/me/");
      set({
        warningPosition: response.data.spend_warning,
        savingsPercent: response.data.savings_percent,
        settingsLoaded: true,
      });
    } catch (error) {
      console.error("Error fetching user settings:", error);
    }
  },

  updateSavingsPercent: async (percent: number) => {
    set({ isLoading: true });
    try {
      await api.put("/settings/preferences/", {
        savings_percent: percent,
      });
      set({ savingsPercent: percent });
    } catch (error) {
      console.error("Error updating savings percent:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  deleteAccount: async (accountId: number) => {
    set({ isLoading: true });
    try {
      await api.delete(`/accounts/${accountId}`);
      set({ accountsLoaded: false });
      await get().fetchAccounts();
    } catch (error) {
      console.error("Error deleting account:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  syncTransactions: async () => {
    try {
      await api.post("/plaid/sync-transactions/");
    } catch (error) {
      console.error("Error triggering transaction sync:", error);
    }
  },

  fetchBudgets: async () => {
    try {
      const response = await api.get("/budgets");
      set({ budgets: response.data, budgetsLoaded: true });
    } catch (error) {
      console.error("Error fetching budgets:", error);
    }
  },

  addBudget: async (budget) => {
    set({ isLoading: true });
    try {
      await api.post("/budgets", budget);
      await get().fetchBudgets();
    } catch (error) {
      console.error("Error creating budget:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  updateBudget: async (budgetId, budget) => {
    set({ isLoading: true });
    try {
      await api.put(`/budgets/${budgetId}`, budget);
      await get().fetchBudgets();
    } catch (error) {
      console.error("Error updating budget:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  deleteBudget: async (budgetId) => {
    set({ isLoading: true });
    try {
      await api.delete(`/budgets/${budgetId}`);
      await get().fetchBudgets();
    } catch (error) {
      console.error("Error deleting budget:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  fetchNetWorth: async () => {
    try {
      const response = await api.get("/networth");
      set({ netWorth: response.data, netWorthLoaded: true });
    } catch (error) {
      console.error("Error fetching net worth:", error);
    }
  },

  fetchProjectedTransactions: async () => {
    try {
      const response = await api.get("/recurring/projected");
      set({ projectedTransactions: response.data, projectedLoaded: true });
    } catch (error) {
      console.error("Error fetching projected transactions:", error);
    }
  },

  fetchNotifications: async () => {
    try {
      const response = await api.get("/notifications");
      set({
        notifications: response.data.items,
        unreadCount: response.data.unread_count,
        notificationsLoaded: true,
      });
    } catch (error) {
      console.error("Error fetching notifications:", error);
    }
  },

  markNotificationRead: async (notificationId: number) => {
    try {
      await api.put(`/notifications/${notificationId}/read`);
      set((state) => ({
        notifications: state.notifications.map((n) =>
          n.id === notificationId ? { ...n, read: true } : n
        ),
        unreadCount: Math.max(0, state.unreadCount - 1),
      }));
    } catch (error) {
      console.error("Error marking notification read:", error);
    }
  },

  markAllNotificationsRead: async () => {
    try {
      await api.put("/notifications/read-all");
      set((state) => ({
        notifications: state.notifications.map((n) => ({ ...n, read: true })),
        unreadCount: 0,
      }));
    } catch (error) {
      console.error("Error marking all notifications read:", error);
    }
  },

  fetchSubscriptions: async () => {
    try {
      const response = await api.get("/subscriptions");
      set({ subscriptions: response.data, subscriptionsLoaded: true });
    } catch (error) {
      console.error("Error fetching subscriptions:", error);
    }
  },

  changePassword: async (currentPassword: string, newPassword: string) => {
    set({ isLoading: true });
    try {
      await api.put("/users/me/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
    } catch (error) {
      console.error("Error changing password:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },
}));
