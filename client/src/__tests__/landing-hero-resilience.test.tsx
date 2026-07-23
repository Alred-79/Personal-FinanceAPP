import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/pages/Landing/coin/CoinSceneLazy", () => ({
  CoinStage: () => <div aria-label="Decorative coin" />,
}));
vi.mock("@/hooks/useEnvironment", () => ({
  usePointerFine: () => false,
  useReducedMotion: () => false,
}));

import { Hero } from "@/pages/Landing/sections/Hero";

afterEach(cleanup);

describe("landing hero resilience", () => {
  it("renders the promise and primary action visibly without waiting for motion", () => {
    render(
      <MemoryRouter>
        <Hero />
      </MemoryRouter>
    );

    const heading = screen.getByRole("heading", { name: /Know what’s safe/i });
    const action = screen.getByRole("link", { name: /Open your ledger — free/i });
    expect(heading).toBeVisible();
    expect(action).toBeVisible();
    expect(heading).not.toHaveStyle({ opacity: "0" });
    expect(action).not.toHaveStyle({ opacity: "0" });
  });
});
