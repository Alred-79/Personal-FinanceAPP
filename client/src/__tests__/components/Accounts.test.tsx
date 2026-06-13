import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { fetchAccounts, addAccount, deleteAccount, toastSpy, accounts } =
  vi.hoisted(() => {
    // A store-owned transactions array we can check for in-render mutation.
    const accounts = [
      {
        id: 1,
        name: "Checking",
        type: "checking",
        balance: 500,
        last_updated: "2026-06-01",
        transactions: [
          { id: 11, date: "2026-03-01", amount: 10, type: "expense" },
          { id: 12, date: "2026-01-01", amount: 20, type: "income" },
          { id: 13, date: "2026-02-01", amount: 5, type: "expense" },
        ],
      },
    ];
    return {
      fetchAccounts: vi.fn(),
      addAccount: vi.fn(),
      deleteAccount: vi.fn(),
      toastSpy: vi.fn(),
      accounts,
    };
  });

vi.mock("@/store/store", () => ({
  useStore: () => ({
    accounts,
    isLoading: false,
    fetchAccounts,
    addAccount,
    deleteAccount,
  }),
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import Accounts from "@/pages/Accounts/Accounts";

beforeEach(() => {
  toastSpy.mockReset();
});
afterEach(() => cleanup());

describe("Accounts render mutation", () => {
  it("does not mutate the store's transactions array order during render", () => {
    // Snapshot the original order before render.
    const before = accounts[0].transactions.map((t) => t.id);
    expect(before).toEqual([11, 12, 13]);

    render(
      <MemoryRouter>
        <Accounts />
      </MemoryRouter>
    );

    // The chart sorts by date ascending. If render used `.sort()` directly it
    // would have reordered the store array in place; a non-mutating `[...].sort`
    // leaves the source untouched.
    const after = accounts[0].transactions.map((t) => t.id);
    expect(after).toEqual([11, 12, 13]);
  });
});
