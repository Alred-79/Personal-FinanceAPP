import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiDelete = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    delete: (...args: unknown[]) => apiDelete(...args),
  },
}));

import MerchantAliasManager from "@/pages/Subscriptions/MerchantAliasManager";

const descriptors = [
  { descriptor: "ACME HOSTING", normalized_key: "acme hosting" },
  { descriptor: "Acme Cloud", normalized_key: "acme cloud" },
];

function mockLoads(aliases: unknown[] = []) {
  apiGet.mockImplementation((url: string) =>
    Promise.resolve({
      data: url.includes("descriptors") ? descriptors : aliases,
    })
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiDelete.mockReset();
  apiPost.mockResolvedValue({ data: {} });
  apiDelete.mockResolvedValue({ data: null });
  mockLoads();
});
afterEach(cleanup);

describe("MerchantAliasManager", () => {
  it("requires and sends an explicit, directional confirmation", async () => {
    const onChanged = vi.fn();
    render(<MerchantAliasManager onChanged={onChanged} />);

    expect(
      screen.getByText(/does not verify a company.s identity/i)
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getAllByRole("option", { name: "ACME HOSTING" })
      ).toHaveLength(2)
    );

    fireEvent.change(screen.getByLabelText("Description to group"), {
      target: { value: "ACME HOSTING" },
    });
    fireEvent.change(screen.getByLabelText("Group under"), {
      target: { value: "Acme Cloud" },
    });
    const button = screen.getByRole("button", { name: "Confirm group" });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Confirm merchant grouping"));
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/merchant-aliases/", {
        alias_descriptor: "ACME HOSTING",
        canonical_descriptor: "Acme Cloud",
        confirmed: true,
      })
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("lists active groups and exposes a reversible undo", async () => {
    mockLoads([
      {
        id: 9,
        alias_key: "acme hosting",
        canonical_key: "acme cloud",
        canonical_label: "Acme Cloud",
        source: "user",
        active: true,
        created_at: null,
      },
    ]);
    render(<MerchantAliasManager />);

    const undo = await screen.findByRole("button", { name: "Undo" });
    fireEvent.click(undo);
    await waitFor(() =>
      expect(apiDelete).toHaveBeenCalledWith("/merchant-aliases/9/")
    );
  });
});
