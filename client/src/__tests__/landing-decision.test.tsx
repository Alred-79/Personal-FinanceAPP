import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { DecisionLab } from "@/pages/Landing/sections/DecisionLab";
import {
  DEMO_SCENARIOS,
  scenarioNet,
  simulate,
} from "@/pages/Landing/sections/forecast/sim";

function scenario(key: string) {
  const found = DEMO_SCENARIOS.find((item) => item.key === key);
  if (!found) throw new Error(`Missing scenario ${key}`);
  return found;
}

describe("landing Decision Lab model", () => {
  it("is deterministic and keeps every modeled band ordered", () => {
    const a = simulate();
    const b = simulate();

    expect(a).toEqual(b);
    for (let day = 0; day < a.low.length; day += 1) {
      expect(a.low[day]).toBeLessThanOrEqual(a.med[day]);
      expect(a.med[day]).toBeLessThanOrEqual(a.high[day]);
    }
    expect(a.troughLow).toBeLessThanOrEqual(a.troughMed);
    expect(a.troughMed).toBeLessThanOrEqual(a.troughHigh);
  });

  it("moves risk in the expected direction without mutating the overlay", () => {
    const baseline = simulate();
    const flightNet = scenarioNet(scenario("flight"));
    const frozenCopy = [...flightNet];
    const flight = simulate({ scenarioNet: flightNet });
    const rent = simulate({ scenarioNet: scenarioNet(scenario("rent-rise")) });
    const delay = simulate({ scenarioNet: scenarioNet(scenario("pay-delay")) });
    const cancel = simulate({ scenarioNet: scenarioNet(scenario("cancel-bill")) });

    expect(flightNet).toEqual(frozenCopy);
    expect(flight.troughMed).toBeLessThan(baseline.troughMed);
    expect(rent.troughMed).toBeLessThan(baseline.troughMed);
    expect(delay.troughMed).toBeLessThan(baseline.troughMed);
    expect(cancel.troughMed).toBeGreaterThanOrEqual(baseline.troughMed);
    expect(flight.prob).toBeGreaterThanOrEqual(baseline.prob);
    expect(cancel.prob).toBeLessThanOrEqual(baseline.prob);
  });
});

describe("landing Decision Lab interaction", () => {
  it("starts with the flight decision and updates one scenario at a time", () => {
    render(
      <MemoryRouter>
        <DecisionLab />
      </MemoryRouter>
    );

    const flight = screen.getByRole("button", { name: /Buy a \$600 flight/i });
    const cancel = screen.getByRole("button", { name: /Cancel a \$130 bill/i });

    expect(flight).toHaveAttribute("aria-pressed", "true");
    expect(cancel).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("−$600 vs. baseline")).toBeInTheDocument();

    fireEvent.click(cancel);

    expect(flight).toHaveAttribute("aria-pressed", "false");
    expect(cancel).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("+$130 vs. baseline")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run this with my numbers/i })).toHaveAttribute(
      "href",
      "/login"
    );
  });
});
