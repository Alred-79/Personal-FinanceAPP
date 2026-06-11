import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));

import NetWorthCard from "@/components/custom/Overview/NetWorthCard";
import { useStore } from "@/store/store";

describe("NetWorthCard", () => {
  beforeEach(() => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({ netWorth: [] });
  });

  it("renders without crashing with empty netWorth", () => {
    render(<NetWorthCard />);
    expect(screen.getByText(/no snapshots/i)).toBeInTheDocument();
  });

  it("shows empty state text when netWorth is empty", () => {
    render(<NetWorthCard />);
    expect(screen.getByText("-- no snapshots --")).toBeInTheDocument();
  });

  it("shows the latest net worth value when data is present", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      netWorth: [
        { date: "2026-05-01", total: 1200 },
        { date: "2026-06-01", total: 1500 },
      ],
    });
    render(<NetWorthCard />);
    expect(screen.getByText("$1,500.00")).toBeInTheDocument();
  });

  it("renders a recharts svg when data is present", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      netWorth: [{ date: "2026-06-01", total: 1000 }],
    });
    const { container } = render(<NetWorthCard />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("shows the card title", () => {
    render(<NetWorthCard />);
    expect(screen.getByText(/net worth/i)).toBeInTheDocument();
  });

  it("uses the last point total when multiple data points exist", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      netWorth: [
        { date: "2026-01-01", total: 500 },
        { date: "2026-06-01", total: 9999 },
      ],
    });
    render(<NetWorthCard />);
    expect(screen.getByText("$9,999.00")).toBeInTheDocument();
  });
});
