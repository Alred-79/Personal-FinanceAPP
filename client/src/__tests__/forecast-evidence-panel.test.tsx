import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn().mockResolvedValue({
      data: {
        descriptive_only: true,
        label: "Forecast evidence pilot — descriptive, not calibration",
        capture: {
          first_date: "2026-07-01",
          last_date: "2026-07-23",
          observed_days: 22,
          scheduled_days: 23,
          completeness: 22 / 23,
          eligible_days: 20,
        },
        horizons: [7, 14, 30].map((horizon) => ({
          horizon_days: horizon,
          counts: { valid: 2, pending: 1 },
          invalid_reasons: {},
          all_origins: {
            sample_count: 2,
            observed_coverage: 0.5,
            coverage_95pct_interval: [0.09, 0.91],
            mean_interval_width: 125,
            mean_winkler_score: 250,
            overdraft_event_count: 0,
            overdraft_event_prevalence: 0,
          },
          predeclared_disjoint_origins: {
            sample_count: 1,
            observed_coverage: 1,
            coverage_95pct_interval: [0.21, 1],
            mean_interval_width: 125,
            mean_winkler_score: 125,
            overdraft_event_count: 0,
            overdraft_event_prevalence: 0,
          },
        })),
        caveats: [],
      },
    }),
  },
}));

import ForecastEvidencePanel from "@/pages/Forecast/ForecastEvidencePanel";

afterEach(cleanup);

describe("forecast evidence owner panel", () => {
  it("labels observations as descriptive and separates the disjoint sample", async () => {
    render(<ForecastEvidencePanel />);
    expect(await screen.findByText(/Descriptive observations only/i)).toBeInTheDocument();
    expect(screen.getByText(/not calibration and not a deployment gate/i)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Disjoint sample/i })).toBeInTheDocument();
    expect(screen.getByText(/effective sample/i)).toBeInTheDocument();
  });
});
