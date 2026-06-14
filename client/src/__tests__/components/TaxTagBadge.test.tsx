import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { TaxTagBadge } from "@/components/custom/TaxTagBadge/TaxTagBadge";

afterEach(cleanup);

describe("TaxTagBadge", () => {
  it("renders the bucket label", () => {
    render(<TaxTagBadge label="Office expense (Sch C line 18)" />);
    expect(
      screen.getByText(/Office expense \(Sch C line 18\)/)
    ).toBeInTheDocument();
  });

  it("shows the deductible percent when below 100%", () => {
    render(
      <TaxTagBadge label="Meals (Sch C line 24b)" deductibleBps={5000} />
    );
    expect(screen.getByText(/50%/)).toBeInTheDocument();
  });

  it("does not show a percent at 100% deductible", () => {
    render(<TaxTagBadge label="Office" deductibleBps={10000} />);
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument();
  });

  it("renders a personal tag with the outline (muted) styling", () => {
    const { container } = render(
      <TaxTagBadge label="Dinner" businessPersonal="personal" />
    );
    // The personal variant uses muted-foreground ink.
    expect(container.firstChild).toHaveClass("text-muted-foreground");
  });
});
