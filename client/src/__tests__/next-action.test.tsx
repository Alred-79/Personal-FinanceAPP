/**
 * W8 — Neurodivergent mode (client).
 *
 * The single-action surface renders EXACTLY ONE action (or the calm "all set"
 * state) — never a wall of nudges; and the visual jars partition Goal.progress
 * into the named earmark sub-buckets. The home only DEFAULTS to the single
 * surface when the `neurodivergent_mode` feature flag is on.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const apiGet = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import { NextActionSurface } from "@/components/custom/NextAction/NextActionSurface";
import { GoalJars } from "@/components/custom/NextAction/GoalJars";
import type { NextAction, Earmark } from "@/types";

function mockNextAction(payload: NextAction) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/next-action/") return Promise.resolve({ data: payload });
    return Promise.resolve({ data: {} });
  });
}

function renderSurface() {
  return render(
    <MemoryRouter>
      <NextActionSurface />
    </MemoryRouter>
  );
}

beforeEach(() => {
  apiGet.mockReset();
});
afterEach(cleanup);

describe("NextActionSurface", () => {
  it("renders exactly one action when one is returned", async () => {
    mockNextAction({
      has_action: true,
      action_type: "bridge_due",
      entity_id: 7,
      copy: "Follow through on the $200.00 transfer in your bank.",
      deep_link: "/assisted-actions",
      source: "bridge",
    });
    renderSurface();

    await waitFor(() =>
      expect(screen.getByText(/follow through on the \$200\.00 transfer/i)).toBeInTheDocument()
    );
    // Exactly one CTA link — never a list of competing nudges.
    const ctas = screen.getAllByRole("link");
    expect(ctas).toHaveLength(1);
    expect(screen.queryByText(/all set/i)).not.toBeInTheDocument();
  });

  it("renders the calm 'all set' empty state and no task when nothing is actionable", async () => {
    mockNextAction({
      has_action: false,
      action_type: "all_set",
      entity_id: null,
      copy: "You're all set for today. Nothing needs your attention right now.",
      deep_link: null,
      source: null,
    });
    renderSurface();

    // The headline (the EmptyState title) reads "You're all set".
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /you're all set/i })).toBeInTheDocument()
    );
    // No CTA — it never invents a task / a place to go.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    // No-shame copy.
    expect(screen.queryByText(/broken|failed|behind/i)).not.toBeInTheDocument();
  });
});

describe("GoalJars", () => {
  const earmarks: Earmark[] = [
    { id: 1, goal_id: 1, name: "Deposit", amount: 200, amount_cents: 20000 },
    { id: 2, goal_id: 1, name: "Movers", amount: 100, amount_cents: 10000 },
  ];

  it("renders a named partition per earmark plus an unallocated remainder", () => {
    render(<GoalJars progress={400} earmarks={earmarks} />);
    // Each named jar appears in the legend.
    expect(screen.getByText("Deposit")).toBeInTheDocument();
    expect(screen.getByText("Movers")).toBeInTheDocument();
    // 400 progress − 300 allocated = 100 unallocated.
    expect(screen.getByText("Unallocated")).toBeInTheDocument();
  });

  it("degrades to a plain rail with no legend when there are no earmarks", () => {
    const { container } = render(<GoalJars progress={400} earmarks={[]} />);
    expect(screen.queryByText("Deposit")).not.toBeInTheDocument();
    // No legend at all when there are no jars — just the rail (the role="img").
    expect(screen.queryByText("Unallocated")).not.toBeInTheDocument();
    expect(container.querySelector("ul")).toBeNull();
    expect(screen.getByRole("img")).toBeInTheDocument();
  });
});
