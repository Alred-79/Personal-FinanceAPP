import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";

const { apiGet, apiDelete, toastSpy } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiDelete: vi.fn(),
  toastSpy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: apiGet, delete: apiDelete },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import { LearnedMemory } from "@/components/custom/LearnedMemory/LearnedMemory";

const FACT = {
  key: "savings_intent",
  value: "saving for a house by 2028",
  source: "user" as const,
  confidence: 100,
  pinned: false,
  updated_at: "2026-06-14T00:00:00+00:00",
};

const PREF_FACT = {
  key: "category_preference:Food",
  value: "cares about the 'Food' category (corrects it manually)",
  source: "deterministic" as const,
  confidence: 100,
  pinned: false,
  updated_at: "2026-06-14T00:00:00+00:00",
};

beforeEach(() => {
  apiGet.mockReset();
  apiDelete.mockReset();
  toastSpy.mockReset();
});
afterEach(cleanup);

describe("LearnedMemory", () => {
  it("lists facts with a human label and source", async () => {
    apiGet.mockResolvedValue({ data: { items: [FACT, PREF_FACT] } });
    render(<LearnedMemory />);
    expect(await screen.findByText("Savings goal")).toBeInTheDocument();
    expect(screen.getByText("saving for a house by 2028")).toBeInTheDocument();
    // Prefix key renders a readable label.
    expect(screen.getByText("Category preference · Food")).toBeInTheDocument();
    // Source badge.
    expect(screen.getByText("You told me")).toBeInTheDocument();
  });

  it("shows the empty state with no facts", async () => {
    apiGet.mockResolvedValue({ data: { items: [] } });
    render(<LearnedMemory />);
    expect(await screen.findByText("Nothing on file yet")).toBeInTheDocument();
  });

  it("forgets a fact via the delete endpoint", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiGet.mockResolvedValue({ data: { items: [FACT] } });
    apiDelete.mockResolvedValue({ data: {} });
    render(<LearnedMemory />);
    await screen.findByText("Savings goal");
    fireEvent.click(screen.getByRole("button", { name: /Forget this/i }));
    await waitFor(() =>
      expect(apiDelete).toHaveBeenCalledWith("/memory/savings_intent/")
    );
  });
});
