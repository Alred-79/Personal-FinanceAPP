import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { env, loadCapabilities } = vi.hoisted(() => ({
  env: { reduce: false },
  loadCapabilities: vi.fn(),
}));

vi.mock("@/pages/Landing/coin/CoinSceneLazy", () => ({
  CoinStage: () => <div aria-label="Decorative coin" />,
}));
vi.mock("@/hooks/useEnvironment", () => ({
  usePointerFine: () => false,
  useReducedMotion: () => env.reduce,
}));
vi.mock("@/lib/capabilities", () => ({ loadCapabilities }));

import { Hero } from "@/pages/Landing/sections/Hero";

function renderHero() {
  return render(
    <MemoryRouter>
      <Hero />
    </MemoryRouter>
  );
}

beforeEach(() => {
  env.reduce = false;
  loadCapabilities.mockReset();
  loadCapabilities.mockRejectedValue(new Error("offline"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("landing hero resilience", () => {
  it("renders the promise and primary action visibly without waiting for motion", () => {
    renderHero();

    const heading = screen.getByRole("heading", { name: /safe to spend before payday/i });
    const action = screen.getByRole("link", { name: /Try the demo/i });
    expect(heading).toBeVisible();
    expect(action).toBeVisible();
    expect(heading).not.toHaveStyle({ opacity: "0" });
    expect(action).not.toHaveStyle({ opacity: "0" });
  });

  it("keeps the demo reachable when the capability probe fails", async () => {
    renderHero();
    await act(async () => {});
    expect(screen.getByRole("link", { name: /Try the demo/i })).toHaveAttribute(
      "href",
      expect.stringMatching(/^https:\/\/.+\/login\?demo=1$/)
    );
  });

  it("shows the arithmetic from balance to safe-to-spend on the page", () => {
    renderHero();
    const ledger = screen.getByText("Safe to spend until payday").closest("dl")!;
    for (const figure of ["$3,480.18", "−$1,650.00", "−$412.00", "−$208.00", "$1,210.18"]) {
      expect(within(ledger).getByText(figure)).toBeInTheDocument();
    }
  });
});

describe("the two-sided coin", () => {
  it("turns itself over to the safe-to-spend side once", () => {
    vi.useFakeTimers();
    renderHero();
    expect(screen.getByRole("radio", { name: "Bank balance" })).toHaveAttribute("aria-checked", "true");

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("radio", { name: "Safe to spend" })).toHaveAttribute("aria-checked", "true");
  });

  it("lets the visitor flip it, and stops the automatic turn once they have", () => {
    vi.useFakeTimers();
    renderHero();
    fireEvent.click(screen.getByRole("radio", { name: "Safe to spend" }));
    fireEvent.click(screen.getByRole("radio", { name: "Bank balance" }));

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("radio", { name: "Bank balance" })).toHaveAttribute("aria-checked", "true");
  });

  it("starts on the answer under reduced motion", () => {
    env.reduce = true;
    renderHero();
    expect(screen.getByRole("radio", { name: "Safe to spend" })).toHaveAttribute("aria-checked", "true");
  });
});
