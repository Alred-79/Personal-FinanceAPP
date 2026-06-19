/**
 * W9 — The Rule Book (client).
 *
 * The standalone management surface lists EVERY rule the user owns — including
 * the auto-created W4/W5/W7 rules that were previously invisible — and lets the
 * user pause/resume (PATCH) or delete (DELETE) each one. Pausing is optimistic
 * and hits the dedicated toggle endpoint so a paused rule stops firing on the
 * next transaction.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { apiGet, apiPatch, apiDelete, toastSpy } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  toastSpy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: apiGet, patch: apiPatch, delete: apiDelete, post: vi.fn(), put: vi.fn() },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import Rules from "@/pages/Rules/Rules";

// A roundup rule (goal-scoped, embedded today) and a Tax-Reserve allocate rule
// (auto-created by W5) — the management surface must show BOTH.
const ROUNDUP_RULE = {
  id: 1,
  name: "Round up to $1",
  enabled: true,
  conditions: [],
  action_type: "roundup",
  action_params: { nearest: "1" },
  target_kind: "goal",
  target_id: 10,
  priority: 0,
};
const TAX_RESERVE_RULE = {
  id: 2,
  name: "Tax Reserve",
  enabled: true,
  conditions: [
    { field: "type", op: "eq", value: "income" },
    { field: "source_type", op: "eq", value: "self_employment" },
  ],
  action_type: "allocate",
  action_params: { pct: 25 },
  target_kind: "goal",
  target_id: 20,
  priority: 0,
};

function mockRules(rules: unknown[], goals: unknown[] = []) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/rules/") return Promise.resolve({ data: rules });
    if (url === "/goals/") return Promise.resolve({ data: goals });
    return Promise.resolve({ data: {} });
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Rules />
    </MemoryRouter>
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiPatch.mockReset();
  apiDelete.mockReset();
  toastSpy.mockReset();
});
afterEach(cleanup);

describe("The Rule Book", () => {
  it("lists ALL rules — embedded AND auto-created (W4/W5/W7)", async () => {
    mockRules([ROUNDUP_RULE, TAX_RESERVE_RULE], [
      { id: 10, name: "Vault" },
      { id: 20, name: "Tax Reserve" },
    ]);
    renderPage();
    expect(await screen.findByText("Round up to $1")).toBeInTheDocument();
    expect(screen.getByText("Tax Reserve")).toBeInTheDocument();
    // No target filter is sent — the page asks for the full set.
    expect(apiGet).toHaveBeenCalledWith("/rules/");
    // The auto-created allocate rule is described with its goal + percent.
    expect(screen.getByText(/25% of each matching transaction/)).toBeInTheDocument();
  });

  it("shows the empty state when there are no rules", async () => {
    mockRules([]);
    renderPage();
    expect(await screen.findByText("No rules on the books")).toBeInTheDocument();
  });

  it("pauses a rule via the dedicated toggle endpoint (stops firing)", async () => {
    mockRules([ROUNDUP_RULE], [{ id: 10, name: "Vault" }]);
    apiPatch.mockResolvedValue({ data: { ...ROUNDUP_RULE, enabled: false } });
    renderPage();
    const toggle = await screen.findByTestId("rule-toggle-1");
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(apiPatch).toHaveBeenCalledWith("/rules/1/", { enabled: false })
    );
  });

  it("deletes a rule", async () => {
    mockRules([ROUNDUP_RULE], [{ id: 10, name: "Vault" }]);
    apiDelete.mockResolvedValue({ data: { message: "ok" } });
    renderPage();
    const del = await screen.findByTestId("rule-delete-1");
    fireEvent.click(del);
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith("/rules/1/"));
    await waitFor(() =>
      expect(screen.queryByText("Round up to $1")).not.toBeInTheDocument()
    );
  });
});
