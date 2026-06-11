import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));
vi.mock("@/hooks/responsive", () => ({ useIsMobile: () => false }));
vi.mock("@/components/custom/TransactionItem/TransactionItem", () => ({
  default: ({ transaction }: { transaction: { title: string } }) => (
    <div data-testid="transaction-item">{transaction.title}</div>
  ),
}));
vi.mock("@/components/custom/TransactionDialog/TransactionDialog", () => ({
  TransactionDialog: () => <div data-testid="transaction-dialog" />,
}));
// CSS modules are handled automatically by Vitest (returns proxy object)

import TransactionsCard from "@/components/custom/Overview/TransactionsCard";
import { useStore } from "@/store/store";

const mockStore = (overrides = {}) => {
  (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
    recentTransactions: [],
    addTransaction: vi.fn(),
    deleteTransaction: vi.fn(),
    ...overrides,
  });
};

describe("TransactionsCard", () => {
  beforeEach(() => mockStore());

  it("renders without crashing when transactions are empty", () => {
    render(<TransactionsCard />);
    expect(screen.getByTestId("transaction-dialog")).toBeInTheDocument();
  });

  it("does not render any transaction items when list is empty", () => {
    render(<TransactionsCard />);
    expect(screen.queryAllByTestId("transaction-item")).toHaveLength(0);
  });

  it("renders N transaction items when store has N items", () => {
    mockStore({
      recentTransactions: [
        { id: 1, title: "Coffee", amount: 4.5, date: "2026-06-01", category: "Food", type: "expense" },
        { id: 2, title: "Salary", amount: 3000, date: "2026-06-01", category: "Income", type: "income" },
      ],
    });
    render(<TransactionsCard />);
    expect(screen.getAllByTestId("transaction-item")).toHaveLength(2);
  });

  it("renders transaction title text", () => {
    mockStore({
      recentTransactions: [
        { id: 1, title: "Netflix", amount: 15, date: "2026-06-01", category: "Entertainment", type: "expense" },
      ],
    });
    render(<TransactionsCard />);
    expect(screen.getByText("Netflix")).toBeInTheDocument();
  });
});
