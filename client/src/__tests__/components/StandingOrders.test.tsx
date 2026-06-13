import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";

const { apiGet, apiPost, apiPut, apiDelete, toastSpy } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  toastSpy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: apiGet, post: apiPost, put: apiPut, delete: apiDelete },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import { StandingOrders } from "@/components/custom/StandingOrders/StandingOrders";

const CATEGORIZE_RULE = {
  id: 3,
  name: "Re-file Shopping → Groceries",
  enabled: true,
  conditions: [{ field: "category", op: "eq", value: "Shopping" }],
  action_type: "categorize" as const,
  action_params: { category: "Groceries" },
  target_kind: null,
  target_id: null,
  priority: 0,
};

const GOAL_RULE = {
  id: 5,
  name: "Round up to $1",
  enabled: true,
  conditions: [],
  action_type: "roundup" as const,
  action_params: { nearest: "1" },
  target_kind: "goal",
  target_id: 2,
  priority: 0,
};

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPut.mockReset();
  apiDelete.mockReset();
  toastSpy.mockReset();
});
afterEach(cleanup);

describe("StandingOrders", () => {
  it("renders the register and marks goal-bound rules as managed elsewhere", async () => {
    apiGet.mockResolvedValue({ data: [CATEGORIZE_RULE, GOAL_RULE] });
    render(<StandingOrders />);
    expect(await screen.findByText("Re-file Shopping → Groceries")).toBeInTheDocument();
    expect(screen.getByText("Round up to $1")).toBeInTheDocument();
    // The goal-bound rule is read-only here.
    expect(screen.getByText("via Goal dialog")).toBeInTheDocument();
  });

  it("shows the empty state with no rules", async () => {
    apiGet.mockResolvedValue({ data: [] });
    render(<StandingOrders />);
    expect(await screen.findByText("No standing orders")).toBeInTheDocument();
  });

  it("creates a categorize rule", async () => {
    apiGet.mockResolvedValue({ data: [] });
    apiPost.mockResolvedValue({ data: {} });
    render(<StandingOrders />);
    await screen.findByText("No standing orders");

    fireEvent.click(screen.getByRole("button", { name: /Enter Order/i }));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        "/rules/",
        expect.objectContaining({ action_type: "categorize" })
      )
    );
  });

  it("toggles a rule's enabled state", async () => {
    apiGet.mockResolvedValue({ data: [CATEGORIZE_RULE] });
    apiPut.mockResolvedValue({ data: {} });
    render(<StandingOrders />);
    await screen.findByText("Re-file Shopping → Groceries");
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(apiPut).toHaveBeenCalledWith(
        "/rules/3/",
        expect.objectContaining({ enabled: false })
      )
    );
  });
});
