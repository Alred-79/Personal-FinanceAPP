import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const fetchGoals = vi.fn();
vi.mock("@/store/store", () => ({
  useStore: (selector: (state: unknown) => unknown) => selector({
    goals: [{ id: 1, name: "Emergency cushion", completed: false }],
    goalsLoaded: true,
    fetchGoals,
  }),
}));

vi.mock("@/lib/api", () => ({
  default: { post: vi.fn() },
}));

import PlanComposerPanel from "@/pages/Forecast/PlanComposerPanel";

afterEach(cleanup);

describe("soft-allocation composer", () => {
  it("keeps the non-movement disclosure visible and exposes no execution controls", () => {
    render(<PlanComposerPanel />);
    expect(screen.getByText(/Soft labels only—nothing moves/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /commit/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^apply/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /preview drafts/i })).toBeInTheDocument();
  });
});
