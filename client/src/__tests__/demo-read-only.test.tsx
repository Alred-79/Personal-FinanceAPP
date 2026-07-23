import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { DemoReadOnlyNotice } from "@/components/layout/AppShell";

afterEach(cleanup);

describe("shared demo read-only notice", () => {
  it("explains what remains interactive in a confirmed demo session", () => {
    render(<DemoReadOnlyNotice visible />);

    expect(
      screen.getByRole("complementary", { name: "Sample data access" })
    ).toHaveTextContent("Sample data · read-only.");
    expect(screen.getByText(/run decision or rule previews/i)).toBeInTheDocument();
    expect(screen.getByText(/create your own ledger/i)).toBeInTheDocument();
  });

  it("does not label an ordinary ledger as sample data", () => {
    render(<DemoReadOnlyNotice visible={false} />);

    expect(screen.queryByText(/Sample data · read-only/i)).not.toBeInTheDocument();
  });
});
