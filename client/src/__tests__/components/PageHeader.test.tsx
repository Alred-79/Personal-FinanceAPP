import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PageHeader from "@/components/layout/PageHeader";

describe("PageHeader", () => {
  it("renders the title text", () => {
    render(<PageHeader title="Overview" />);
    expect(screen.getByText("Overview")).toBeInTheDocument();
  });

  it("renders the >_ terminal prefix", () => {
    render(<PageHeader title="Overview" />);
    expect(screen.getByText(">_")).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    render(<PageHeader title="T" description="Some description" />);
    expect(screen.getByText("Some description")).toBeInTheDocument();
  });

  it("does not render description when not provided", () => {
    render(<PageHeader title="T" />);
    expect(screen.queryByText(/description/i)).toBeNull();
  });

  it("renders actions slot content", () => {
    render(<PageHeader title="T" actions={<button>Add</button>} />);
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("renders the blinking cursor character", () => {
    render(<PageHeader title="T" />);
    expect(screen.getByText("▋")).toBeInTheDocument();
  });

  it("matches snapshot", () => {
    const { container } = render(<PageHeader title="Test" description="Desc" />);
    expect(container).toMatchSnapshot();
  });
});
