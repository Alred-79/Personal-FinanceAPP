import { describe, it, expect, afterEach } from "vitest";
import { act } from "@testing-library/react";
import { useStore } from "@/store/store";

afterEach(() => {
  // Reset selectedAccountId between tests
  act(() => {
    useStore.getState().setSelectedAccountId("all");
  });
});

describe("Store defaults", () => {
  it("selectedAccountId defaults to 'all'", () => {
    expect(useStore.getState().selectedAccountId).toBe("all");
  });

  it("isLoggedIn defaults to false", () => {
    expect(useStore.getState().isLoggedIn).toBe(false);
  });

  it("isLoading defaults to false", () => {
    expect(useStore.getState().isLoading).toBe(false);
  });

  it("transactions defaults to empty array", () => {
    expect(useStore.getState().transactions).toEqual([]);
  });

  it("budgets defaults to empty array", () => {
    expect(useStore.getState().budgets).toEqual([]);
  });

  it("netWorth defaults to empty array", () => {
    expect(useStore.getState().netWorth).toEqual([]);
  });

  it("goals defaults to empty array", () => {
    expect(useStore.getState().goals).toEqual([]);
  });

  it("recentTransactions defaults to empty array", () => {
    expect(useStore.getState().recentTransactions).toEqual([]);
  });

  it("notifications defaults to empty array", () => {
    expect(useStore.getState().notifications).toEqual([]);
  });

  it("subscriptions defaults to empty array", () => {
    expect(useStore.getState().subscriptions).toEqual([]);
  });

  it("user defaults to null", () => {
    expect(useStore.getState().user).toBeNull();
  });
});

describe("setSelectedAccountId", () => {
  it("updates selectedAccountId to a given string", () => {
    act(() => {
      useStore.getState().setSelectedAccountId("123");
    });
    expect(useStore.getState().selectedAccountId).toBe("123");
  });

  it("can be reset back to 'all'", () => {
    act(() => {
      useStore.getState().setSelectedAccountId("42");
    });
    act(() => {
      useStore.getState().setSelectedAccountId("all");
    });
    expect(useStore.getState().selectedAccountId).toBe("all");
  });
});
