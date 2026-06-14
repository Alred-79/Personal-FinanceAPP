import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

const { navigate, fetchGoals } = vi.hoisted(() => ({
  navigate: vi.fn(),
  fetchGoals: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom"
  );
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("@/store/store", () => ({
  useStore: () => ({
    goals: [
      {
        id: 42,
        name: "Emergency Fund",
        description: "",
        amount: 1000,
        progress: 250,
        deadline: new Date("2027-06-01"),
        completed: false,
      },
    ],
    goalsLoaded: true,
    isLoading: false,
    fetchGoals,
    addGoal: vi.fn(),
    updateGoal: vi.fn(),
    deleteGoal: vi.fn(),
    updateGoalProgress: vi.fn(),
  }),
}));

vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}));

import Goals from "@/pages/Goals/Goals";

beforeEach(() => navigate.mockClear());
afterEach(() => cleanup());

describe("Goals — What if entry", () => {
  it("navigates to /forecast with the goal id", () => {
    render(<Goals />);
    const whatIf = screen.getByRole("button", { name: /What if/i });
    fireEvent.click(whatIf);
    expect(navigate).toHaveBeenCalledWith("/forecast?goal=42");
  });
});
