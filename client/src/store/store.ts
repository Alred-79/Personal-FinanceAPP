import { create } from "zustand";
import {
  Transaction,
  Expense,
  Notification,
  Subscription,
  Account,
  Frequency,
  ReceiptDraft,
  ForecastPoint,
  Scenario,
  ScenarioDiff,
  ScenarioCompareResult,
  ScenarioMutationPayload,
  CommittedPlan,
  ImportSession,
  ImportRow,
} from "../types";
import api from "../lib/api";
import { currentWeekRange, toLocalISODate, parseLocalISODate } from "../lib/dates";
import { toast } from "../hooks/useToast";
import { resetGameMode } from "./gameMode";

// ``ForecastPoint`` moved to types/index.ts (so the scenario types can reuse it
// without a store→types→store cycle); re-exported here for existing consumers.
export type { Account, ForecastPoint };

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

export interface Forecast {
  horizon_start: string;
  horizon_end: string;
  starting_balance: number;
  ending_balance: number;
  lowest_balance: number;
  lowest_date: string;
  total_projected_expenses: number;
  total_projected_income?: number;
  will_go_negative: boolean;
  timeline: ForecastPoint[];
}

/** Server-computed Safe-to-Spend (v1 F3): the one number plus its why. */
export interface SafeToSpend {
  available: number;
  horizon_end: string;
  horizon_source: string;
  days_remaining: number;
  daily_plan: number;
  breakdown: {
    current_balance: number;
    upcoming_bills: number;
    projected_income: number;
    goal_earmarks: number;
    goal_contributions: number;
    buffer: number;
  };
  config: {
    horizon: "paycheck" | "month" | "week";
    include_income: boolean;
    include_goals: boolean;
    buffer: number;
  };
}

export interface S2SPrefs {
  s2s_horizon: "paycheck" | "month" | "week";
  s2s_include_income: boolean;
  s2s_include_goals: boolean;
  s2s_buffer: number;
}

import { categoryColor } from "../lib/format";

/**
 * Per-fetcher AbortControllers. A new call aborts the in-flight previous one so
 * a slow, stale response can't overwrite a fresh one (e.g. rapid search typing,
 * fast pagination, flipping the forecast horizon). Module-level because they're
 * shared singletons across the single store instance.
 */
const inflight: Record<string, AbortController | undefined> = {};

/** True for an axios/fetch cancellation we should swallow silently. */
function isAbort(error: unknown): boolean {
  if (error == null || typeof error !== "object") return false;
  const e = error as { name?: string; code?: string };
  return (
    e.name === "CanceledError" ||
    e.name === "AbortError" ||
    e.code === "ERR_CANCELED"
  );
}

interface StoreState {
  transactions: Transaction[];
  recentTransactions: Transaction[];
  expenses: Expense[];
  budgetAllotment: number;
  safeToSpend: SafeToSpend | null;
  s2sPrefs: S2SPrefs;
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
  /** Pillar 3: server-side feature flag for the tax layer (read-only; gates the
   * tax nav entry). False until settings load. */
  taxFeaturesEnabled: boolean;
  budgets: Budget[];
  budgetsLoaded: boolean;
  netWorth: NetWorthPoint[];
  netWorthLoaded: boolean;
  projectedTransactions: ProjectedTransaction[];
  projectedLoaded: boolean;
  forecast: Forecast | null;
  forecastLoaded: boolean;
  forecastHorizon: number;
  notifications: Notification[];
  unreadCount: number;
  notificationsLoaded: boolean;
  subscriptions: Subscription[];
  subscriptionsLoaded: boolean;
  /** Command Deck → "add transaction": a consume-once request the Transactions
   *  page reads to open its TransactionDialog (so the deck never mutates money
   *  directly — the manual form + validation stays the single entry point). */
  addTxnRequested: boolean;

  // Actions
  requestAddTransaction: () => void;
  consumeAddTransaction: () => void;
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
    recurrence?: Frequency;
  }) => Promise<void>;
  scanReceipt: (file: File) => Promise<ReceiptDraft>;
  // Messy-data ingestion (Reconciliation Desk / Import Anything).
  importDocument: (file: File, accountId: number) => Promise<ImportSession>;
  importText: (text: string, accountId: number) => Promise<ImportSession>;
  fetchImportSession: (sessionId: number) => Promise<ImportSession>;
  patchImportRow: (
    sessionId: number,
    rowId: number,
    patch: Partial<Pick<ImportRow, "title" | "amount" | "date" | "category" | "included">>
  ) => Promise<ImportSession>;
  discardImportSession: (sessionId: number) => Promise<void>;
  runDetangle: () => Promise<number>;
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
  fetchSafeToSpend: () => Promise<void>;
  updateS2sPrefs: (prefs: Partial<S2SPrefs>) => Promise<void>;
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

  // Cashflow forecast (balance projected over a horizon)
  fetchForecast: (days?: number) => Promise<void>;

  // Notifications & subscriptions
  fetchNotifications: () => Promise<void>;
  markNotificationRead: (notificationId: number) => Promise<void>;
  markAllNotificationsRead: () => Promise<void>;
  fetchSubscriptions: () => Promise<void>;

  // Scenarios (v6 doc 07) — saved hypotheticals + live evaluate/compare/commit.
  scenarios: Scenario[];
  scenariosLoaded: boolean;
  activeScenarioResult: ScenarioDiff | null;
  compareResult: ScenarioCompareResult | null;
  committedPlan: CommittedPlan | null;
  fetchScenarios: () => Promise<void>;
  createScenario: (name: string, overlay: ScenarioMutationPayload) => Promise<Scenario>;
  updateScenario: (
    id: number,
    name: string,
    overlay: ScenarioMutationPayload
  ) => Promise<void>;
  deleteScenario: (id: number) => Promise<void>;
  /** Live-evaluate an in-progress (unsaved) overlay; abortable mid-flight. */
  runScenario: (
    overlay: ScenarioMutationPayload,
    opts?: { name?: string; horizonDays?: number }
  ) => Promise<void>;
  compareScenarios: (scenarioIds: number[], horizonDays?: number) => Promise<void>;
  /** Propose→confirm a saved scenario into a standing plan; refetches on success. */
  commitScenario: (scenarioId: number, name: string) => Promise<CommittedPlan>;
}

/**
 * Every non-action field's initial value, in one place. The store seeds itself
 * from this AND logout() resets to it — so a new slice can't be silently
 * forgotten on logout (which is how financial state — Safe-to-Spend, the
 * budget, the selected account — used to leak across a re-login).
 */
const initialState = {
  transactions: [] as Transaction[],
  recentTransactions: [] as Transaction[],
  expenses: [] as Expense[],
  budgetAllotment: 1,
  safeToSpend: null as SafeToSpend | null,
  s2sPrefs: {
    s2s_horizon: "paycheck",
    s2s_include_income: true,
    s2s_include_goals: true,
    s2s_buffer: 0,
  } as S2SPrefs,
  spendOverTime: 1,
  fixedPerMonth: 0,
  warningPosition: 25,
  savingsPercent: 20,
  isLoading: false,
  hasLoaded: false,
  accounts: [] as Account[],
  accountsLoaded: false,
  selectedAccountId: "all",
  transactionsLoaded: false,
  transactionTotal: 0,
  transactionRefreshKey: 0,
  goals: [] as Goal[],
  goalsLoaded: false,
  user: null as User | null,
  userLoaded: false,
  linkToken: null as string | null,
  isLoggedIn: false,
  settingsLoaded: false,
  taxFeaturesEnabled: false,
  budgets: [] as Budget[],
  budgetsLoaded: false,
  netWorth: [] as NetWorthPoint[],
  netWorthLoaded: false,
  projectedTransactions: [] as ProjectedTransaction[],
  projectedLoaded: false,
  forecast: null as Forecast | null,
  forecastLoaded: false,
  forecastHorizon: 30,
  notifications: [] as Notification[],
  unreadCount: 0,
  notificationsLoaded: false,
  subscriptions: [] as Subscription[],
  subscriptionsLoaded: false,
  addTxnRequested: false,
  scenarios: [] as Scenario[],
  scenariosLoaded: false,
  activeScenarioResult: null as ScenarioDiff | null,
  compareResult: null as ScenarioCompareResult | null,
  committedPlan: null as CommittedPlan | null,
};

/**
 * Fields cleared on logout. The user-identity fields (user, isLoggedIn,
 * userLoaded) are spread from initialState too, but logout overrides
 * userLoaded back to false explicitly via the spread (it's already false here).
 */
export const useStore = create<StoreState>((set, get) => ({
  ...initialState,

  // Command Deck → Transactions hand-off (consume-once; see addTxnRequested).
  requestAddTransaction: () => set({ addTxnRequested: true }),
  consumeAddTransaction: () => set({ addTxnRequested: false }),

  setSelectedAccountId: (accountId: string) => {
    set({ selectedAccountId: accountId });
  },

  fetchAccountTransactions: async (accountId: string, params = {}) => {
    // Cancel any in-flight transactions fetch so a slow stale response (e.g.
    // the previous keystroke's search) can't clobber the latest one.
    inflight.transactions?.abort();
    const controller = new AbortController();
    inflight.transactions = controller;
    try {
      const queryParams: Record<string, unknown> = { ...params };
      if (accountId !== "all") {
        queryParams.account_id = accountId;
      }
      const response = await api.get("/transactions", {
        params: queryParams,
        signal: controller.signal,
      });
      const { items, total } = response.data;
      const transactionsWithColors = items.map((t: Transaction) => ({
        ...t,
        backgroundColor: categoryColor(t.category),
      }));
      set({ transactions: transactionsWithColors, transactionTotal: total, transactionsLoaded: true });
    } catch (error) {
      if (isAbort(error)) return; // superseded by a newer request — ignore
      console.error("Error fetching transactions:", error);
      toast({
        variant: "destructive",
        title: "Could not load transactions",
        description: "Please check your connection and try again.",
      });
    } finally {
      if (inflight.transactions === controller) inflight.transactions = undefined;
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

      await get().fetchSafeToSpend();

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
      // Surface a load failure instead of silently showing empty/zeroed cards
      // (which read as "nothing here" rather than "couldn't load").
      toast({
        variant: "destructive",
        title: "Could not load your dashboard",
        description: "Some figures may be missing. Please refresh.",
      });
    }
  },

  fetchSafeToSpend: async () => {
    try {
      const response = await api.get("/spend/safe-to-spend");
      set({ safeToSpend: response.data });
    } catch (error) {
      console.error("Error fetching safe-to-spend:", error);
    }
  },

  updateS2sPrefs: async (prefs) => {
    set({ isLoading: true });
    try {
      await api.put("/settings/preferences/", prefs);
      set((s) => ({ s2sPrefs: { ...s.s2sPrefs, ...prefs } }));
      await get().fetchSafeToSpend();
    } catch (error) {
      console.error("Error updating Safe-to-Spend settings:", error);
      throw error;
    } finally {
      set({ isLoading: false });
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
      toast({
        variant: "destructive",
        title: "Could not load accounts",
        description: "Please check your connection and try again.",
      });
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

  importDocument: async (file: File, accountId: number) => {
    // Multipart upload to the Import Anything endpoint. Like scanReceipt, errors
    // propagate so the UI can surface the server `detail`.
    const form = new FormData();
    form.append("file", file);
    form.append("account_id", String(accountId));
    const { data } = await api.post("/imports/extract", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data as ImportSession;
  },

  importText: async (text: string, accountId: number) => {
    const { data } = await api.post("/imports/extract/text", {
      account_id: accountId,
      text,
    });
    return data as ImportSession;
  },

  fetchImportSession: async (sessionId: number) => {
    const { data } = await api.get(`/imports/sessions/${sessionId}`);
    return data as ImportSession;
  },

  patchImportRow: async (sessionId, rowId, patch) => {
    // Returns the refreshed (re-reconciled) session payload.
    const { data } = await api.patch(
      `/imports/sessions/${sessionId}/rows/${rowId}`,
      patch
    );
    return data as ImportSession;
  },

  discardImportSession: async (sessionId: number) => {
    await api.post(`/imports/sessions/${sessionId}/discard`);
  },

  runDetangle: async () => {
    // Flags transfer/refund/duplicate pairs; returns how many NEW pairings were
    // surfaced (notifications are deduped server-side). Refresh notifications so
    // the bell reflects the new nudges.
    const { data } = await api.post("/imports/detangle/run");
    await get().fetchNotifications?.();
    return (data?.flagged ?? 0) as number;
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

      await get().fetchSafeToSpend();

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
        deadline: parseLocalISODate(goal.date),
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
        date: toLocalISODate(goal.deadline),
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
        date: toLocalISODate(goal.deadline),
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
        date: toLocalISODate(goal.deadline),
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
    // Reset EVERY non-action slice back to its initial value. Spreading
    // initialState (rather than hand-listing fields) guarantees financial
    // state — safeToSpend, s2sPrefs, budgetAllotment, selectedAccountId — is
    // cleared too, so a re-login on the same machine starts from a clean slate
    // instead of flashing the prior session's numbers.
    set({ ...initialState });
    // Reset the game-mode provider to its off default (it fetches once on mount
    // and otherwise never resets) so game chrome doesn't survive logout.
    resetGameMode();
  },

  fetchLinkToken: async () => {
    try {
      const user = get().user;
      if (!user) return;

      // Step 03 made this endpoint authed and removed the user_id param — the
      // server now derives the Plaid client_user_id from the session. Passing
      // ?user_id= would be ignored (or rejected); use the no-param authed form.
      const response = await api.get("/plaid/link-token/");
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
      const response = await api.get("/settings/");
      const prefs = response.data.preferences;
      set({
        warningPosition: prefs.spend_warning,
        savingsPercent: prefs.savings_percent,
        s2sPrefs: {
          s2s_horizon: prefs.s2s_horizon ?? "paycheck",
          s2s_include_income: prefs.s2s_include_income ?? true,
          s2s_include_goals: prefs.s2s_include_goals ?? true,
          s2s_buffer: prefs.s2s_buffer ?? 0,
        },
        taxFeaturesEnabled: response.data.features?.tax_features_enabled ?? false,
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
      // Without this, a backend failure renders as the innocent "Nothing to
      // project yet" empty state — the user can't tell a real outage apart.
      toast({
        variant: "destructive",
        title: "Could not load projections",
        description: "Recurring projections may be incomplete. Please refresh.",
      });
    }
  },

  fetchForecast: async (days = 30) => {
    // Switching horizons fast (30 → 90 → 365) can land responses out of order;
    // abort the previous so the displayed horizon always matches the last click.
    inflight.forecast?.abort();
    const controller = new AbortController();
    inflight.forecast = controller;
    try {
      const response = await api.get("/forecast", {
        params: { days },
        signal: controller.signal,
      });
      set({
        forecast: response.data,
        forecastLoaded: true,
        forecastHorizon: days,
      });
    } catch (error) {
      if (isAbort(error)) return; // superseded by a newer horizon — ignore
      console.error("Error fetching forecast:", error);
      set({ forecastLoaded: true });
      toast({
        variant: "destructive",
        title: "Could not load the forecast",
        description: "Please try again in a moment.",
      });
    } finally {
      if (inflight.forecast === controller) inflight.forecast = undefined;
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

  // ── Scenarios (v6 doc 07) ────────────────────────────────────────────────
  fetchScenarios: async () => {
    try {
      const response = await api.get("/scenarios/");
      set({ scenarios: response.data, scenariosLoaded: true });
    } catch (error) {
      console.error("Error fetching scenarios:", error);
      set({ scenariosLoaded: true });
    }
  },

  createScenario: async (name, overlay) => {
    set({ isLoading: true });
    try {
      const response = await api.post("/scenarios/", { name, overlay });
      set({ scenariosLoaded: false });
      await get().fetchScenarios();
      return response.data as Scenario;
    } catch (error) {
      console.error("Error creating scenario:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  updateScenario: async (id, name, overlay) => {
    set({ isLoading: true });
    try {
      await api.put(`/scenarios/${id}/`, { name, overlay });
      set({ scenariosLoaded: false });
      await get().fetchScenarios();
    } catch (error) {
      console.error("Error updating scenario:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  deleteScenario: async (id) => {
    set({ isLoading: true });
    try {
      await api.delete(`/scenarios/${id}/`);
      set({ scenariosLoaded: false });
      await get().fetchScenarios();
    } catch (error) {
      console.error("Error deleting scenario:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  runScenario: async (overlay, opts = {}) => {
    // The live builder re-runs on every debounced edit; abort the prior run so a
    // slow earlier response can't overwrite the freshest overlay's diff. A
    // dedicated inflight key keeps this independent of the forecast fetch.
    inflight.scenarioRun?.abort();
    const controller = new AbortController();
    inflight.scenarioRun = controller;
    try {
      const response = await api.post(
        "/scenarios/evaluate/",
        {
          name: opts.name ?? "Scenario",
          horizon_days: opts.horizonDays ?? 90,
          overlay,
        },
        { signal: controller.signal }
      );
      set({ activeScenarioResult: response.data });
    } catch (error) {
      if (isAbort(error)) return; // superseded by a newer overlay — ignore
      console.error("Error running scenario:", error);
      toast({
        variant: "destructive",
        title: "Could not run the scenario",
        description: "Please try again in a moment.",
      });
    } finally {
      if (inflight.scenarioRun === controller) inflight.scenarioRun = undefined;
    }
  },

  compareScenarios: async (scenarioIds, horizonDays = 90) => {
    try {
      const response = await api.post("/scenarios/compare/", {
        scenario_ids: scenarioIds,
        horizon_days: horizonDays,
      });
      set({ compareResult: response.data });
    } catch (error) {
      console.error("Error comparing scenarios:", error);
      toast({
        variant: "destructive",
        title: "Could not compare scenarios",
        description: "Please try again in a moment.",
      });
    }
  },

  commitScenario: async (scenarioId, name) => {
    // Two-step gate: propose mints a signed token describing the commit, then
    // confirm runs it. On success the standing rules change the projection and
    // a goal's earmark, so refetch forecast + goals to reflect the new reality.
    set({ isLoading: true });
    try {
      const proposal = await api.post("/assistant/actions/propose/", {
        action: "scenario_commit",
        params: { scenario_id: scenarioId, name },
      });
      const token = proposal.data.token;
      const confirm = await api.post("/assistant/actions/confirm/", { token });
      const result = confirm.data.result as CommittedPlan;
      set({ committedPlan: result });
      set({ forecastLoaded: false, goalsLoaded: false });
      await Promise.all([get().fetchForecast(get().forecastHorizon || 30), get().fetchGoals()]);
      return result;
    } catch (error) {
      console.error("Error committing scenario:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },
}));
