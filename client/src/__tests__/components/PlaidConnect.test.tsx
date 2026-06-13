import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { fetchLinkToken, exchangePublicToken, toastSpy, storeState } = vi.hoisted(
  () => ({
    fetchLinkToken: vi.fn(),
    exchangePublicToken: vi.fn(),
    toastSpy: vi.fn(),
    storeState: { linkToken: "link-tok-123" as string | null },
  })
);

vi.mock("@/store/store", () => ({
  useStore: () => ({
    linkToken: storeState.linkToken,
    fetchLinkToken,
    exchangePublicToken,
  }),
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import { PlaidConnect } from "@/components/custom/PlaidConnect/PlaidConnect";

type OnSuccess = (token: string, meta: { institution: { name: string } }) => void;
let capturedOnSuccess: OnSuccess | null = null;

function installPlaid() {
  capturedOnSuccess = null;
  (window as unknown as { Plaid: unknown }).Plaid = {
    create: (config: { onSuccess: OnSuccess }) => {
      capturedOnSuccess = config.onSuccess;
      return { open: vi.fn(), destroy: vi.fn() };
    },
  };
}

beforeEach(() => {
  fetchLinkToken.mockReset();
  exchangePublicToken.mockReset();
  toastSpy.mockReset();
  storeState.linkToken = "link-tok-123";
  delete (window as unknown as { Plaid?: unknown }).Plaid;
});
afterEach(() => {
  cleanup();
  delete (window as unknown as { Plaid?: unknown }).Plaid;
});

describe("PlaidConnect robustness", () => {
  it("disables Connect until window.Plaid is present, then enables it", async () => {
    // Script not loaded yet → button is disabled with a loading label.
    render(
      <MemoryRouter>
        <PlaidConnect />
      </MemoryRouter>
    );
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn.textContent).toMatch(/preparing/i);

    // Script becomes available → polling picks it up and the button enables.
    act(() => {
      installPlaid();
    });
    await waitFor(() => expect(screen.getByRole("button")).not.toBeDisabled());
    expect(screen.getByRole("button").textContent).toMatch(/connect a bank/i);
  });

  it("surfaces a toast (not a silent stuck state) when the exchange fails", async () => {
    installPlaid();
    exchangePublicToken.mockRejectedValue(new Error("exchange 500"));

    render(
      <MemoryRouter>
        <PlaidConnect />
      </MemoryRouter>
    );

    await waitFor(() => expect(capturedOnSuccess).not.toBeNull());

    // Simulate Plaid Link reporting success → our onSuccess runs the exchange.
    await act(async () => {
      await capturedOnSuccess!("public-token", { institution: { name: "Chase" } });
    });

    expect(exchangePublicToken).toHaveBeenCalledWith("public-token", "Chase");
    const arg = toastSpy.mock.calls.at(-1)?.[0];
    expect(arg?.variant).toBe("destructive");
    expect(String(arg?.title)).toMatch(/could not connect/i);
  });
});
