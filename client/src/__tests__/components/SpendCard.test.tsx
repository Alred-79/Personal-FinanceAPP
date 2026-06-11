import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));

import SpendCard from "@/components/custom/Overview/SpendCard";
import { useStore } from "@/store/store";

describe("SpendCard", () => {
  beforeEach(() => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      spendOverTime: 0,
      budgetAllotment: 0,
    });
  });

  it("renders without crashing", () => {
    render(<SpendCard />);
    expect(screen.getByText(/weekly spend/i)).toBeInTheDocument();
  });

  it("displays spendOverTime formatted as currency", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      spendOverTime: 250.0,
      budgetAllotment: 500,
    });
    render(<SpendCard />);
    expect(screen.getByText("$250.00")).toBeInTheDocument();
  });

  it("displays budgetAllotment in the label", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      spendOverTime: 100,
      budgetAllotment: 400,
    });
    render(<SpendCard />);
    expect(screen.getByText(/\$400\.00/)).toBeInTheDocument();
  });

  it("shows 50.0% when spend is half of budget", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      spendOverTime: 50,
      budgetAllotment: 100,
    });
    render(<SpendCard />);
    expect(screen.getByText(/50\.0%/)).toBeInTheDocument();
  });

  it("shows over-limit warning when spend exceeds budget", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      spendOverTime: 150,
      budgetAllotment: 100,
    });
    render(<SpendCard />);
    expect(screen.getByText(/over weekly limit/i)).toBeInTheDocument();
  });

  it("does not show over-limit warning when within budget", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      spendOverTime: 80,
      budgetAllotment: 100,
    });
    render(<SpendCard />);
    expect(screen.queryByText(/over weekly limit/i)).toBeNull();
  });

  it("shows 0.0% when budgetAllotment is 0", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      spendOverTime: 0,
      budgetAllotment: 0,
    });
    render(<SpendCard />);
    expect(screen.getByText(/0\.0%/)).toBeInTheDocument();
  });
});
