import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { HowItThinks } from "@/pages/Landing/sections/forecast/HowItThinks";
import { LiveForecast } from "@/pages/Landing/sections/forecast/LiveForecast";
import { Vignettes } from "@/pages/Landing/sections/forecast/Vignettes";

afterEach(cleanup);

describe("landing forecast honesty", () => {
  it("describes the browser widget as simulated percentiles, not real-outcome calibration", () => {
    const { container } = render(
      <>
        <HowItThinks />
        <LiveForecast />
      </>
    );
    const text = container.textContent ?? "";

    expect(screen.getByText(/5th–95th simulated range/i)).toBeInTheDocument();
    expect(text).toMatch(/5th–95th percentiles of the modeled paths/i);
    expect(text).not.toMatch(/contains the real outcome/i);
    expect(text).not.toMatch(/calibrated\s*~?90%/i);
    expect(text).toMatch(/modeled paths below \$0/i);
    expect(text).not.toMatch(/chance|probability/i);
  });

  it("gives the chart an accessible description without a calibration claim", () => {
    const { container } = render(<LiveForecast />);
    const chart = container.querySelector("svg[role='img']");
    expect(chart).toHaveAttribute("aria-label", expect.stringMatching(/cash-flow forecast/i));
    expect(chart?.getAttribute("aria-label")).not.toMatch(/calibrat|real outcome/i);
    expect(chart?.getAttribute("aria-label")).toMatch(/modeled paths fall below zero/i);
    expect(chart?.getAttribute("aria-label")).not.toMatch(/chance|probability/i);
  });

  it("keeps the illustrative Safe-to-Spend equation internally consistent", () => {
    render(<Vignettes />);
    expect(screen.getByText("+$150")).toBeInTheDocument();
    expect(screen.getByText("$850")).toBeInTheDocument();
    expect(screen.queryByText("+$1,800")).not.toBeInTheDocument();
  });
});
