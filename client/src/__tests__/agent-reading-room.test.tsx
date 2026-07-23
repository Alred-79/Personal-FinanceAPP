import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AgentReadingRoom } from "@/pages/Landing/sections/AgentReadingRoom";

/**
 * The Reading Room is deliberately deterministic — it demonstrates the MCP
 * surface from a fixed example ledger, with no network and no randomness — so
 * every journey below is exactly reproducible.
 */

/** Drive prefers-reduced-motion, which decides whether the request animates. */
function setReducedMotion(reduce: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? reduce : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function renderRoom() {
  return render(
    <MemoryRouter>
      <AgentReadingRoom />
    </MemoryRouter>
  );
}

/** File a request by its question text. */
function file(question: RegExp) {
  fireEvent.click(screen.getByRole("radio", { name: question }));
}

/** The clause row for a scope id, as a visitor toggles it. */
function clause(scopeId: string): HTMLInputElement {
  const code = screen.getByText(scopeId);
  const label = code.closest("label");
  if (!label) throw new Error(`no clause row for ${scopeId}`);
  return within(label).getByRole("checkbox") as HTMLInputElement;
}

beforeEach(() => setReducedMotion(true));
afterEach(cleanup);

describe("The Agent Reading Room", () => {
  it("states the offer without promising public availability", () => {
    renderRoom();
    expect(
      screen.getByRole("heading", { name: /Your AI can understand the whole ledger/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/Advanced MCP integration/i)).toBeInTheDocument();
    expect(screen.getByText(/confirmed only after sign-in/i)).toBeInTheDocument();
    expect(screen.queryByText(/Available now/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/beta/i)).not.toBeInTheDocument();
    // The disclosure is never buried.
    expect(
      screen.getByText(/Your chosen AI provider receives the information you authorize/i)
    ).toBeInTheDocument();
    // The demo is labelled as an example, not a live call.
    expect(screen.getByText(/not a live API call/i)).toBeInTheDocument();
  });

  it("provides a truthful sign-in path without issuing credentials publicly", () => {
    renderRoom();
    const configure = screen.getByRole("link", { name: /Configure AI access/i });
    expect(configure).toHaveAttribute("href", "/login?next=%2Fsettings%3Ftab%3Dagent-keys");
    expect(screen.queryByRole("link", { name: /Connect your AI/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /See how access works/i })).toBeInTheDocument();
  });

  it("answers a fully-scoped request and files an allow receipt", async () => {
    renderRoom();
    file(/Can I buy a \$600 flight/i);

    expect(await screen.findByText("Yes — with $610.18 of room left.")).toBeInTheDocument();
    expect(screen.getByText("$610.18")).toBeInTheDocument();
    expect(screen.getByText("−$600.00")).toBeInTheDocument();

    // Every station cleared, in order.
    for (const stamp of ["Received", "Scoped", "Narrowed", "Read-only", "Filed", "Entered"]) {
      expect(screen.getAllByText(stamp).length).toBeGreaterThan(0);
    }
    // The receipt carries exactly what the audit log stores.
    expect(screen.getByText("run_what_if")).toBeInTheDocument();
    expect(screen.getByText("Allow")).toBeInTheDocument();
    expect(screen.getByText(/Inputs are hashed, never stored raw/i)).toBeInTheDocument();
  });

  it("stops an under-scoped request at the gate and names what's missing", async () => {
    renderRoom();
    file(/Can I buy a \$600 flight/i);
    await screen.findByText("Yes — with $610.18 of room left.");

    // Take away a scope the request depends on.
    fireEvent.click(clause("read:forecast"));

    expect(await screen.findByText(/Denied · scope required/i)).toBeInTheDocument();
    // Stamped at the gate AND sealed on the docket — the refusal is legible twice.
    expect(screen.getAllByText("Denied")).toHaveLength(2);
    // The data was never reached, and the reason is specific.
    expect(screen.getByText(/never reached your data/i)).toBeInTheDocument();
    expect(screen.getByText("Deny")).toBeInTheDocument();
    // Stations past the gate never stamp.
    expect(screen.queryByText("Read-only")).not.toBeInTheDocument();
    expect(screen.queryByText("Entered")).not.toBeInTheDocument();
    // And the answer is gone.
    expect(screen.queryByText("Yes — with $610.18 of room left.")).not.toBeInTheDocument();
  });

  it("lets the visitor grant the missing clause and re-file in one tap", async () => {
    renderRoom();
    file(/Can I buy a \$600 flight/i);
    await screen.findByText("Yes — with $610.18 of room left.");
    fireEvent.click(clause("read:forecast"));
    await screen.findByText(/Denied · scope required/i);

    fireEvent.click(screen.getByRole("button", { name: /Grant Forecast and file it again/i }));

    expect(await screen.findByText("Yes — with $610.18 of room left.")).toBeInTheDocument();
    expect(clause("read:forecast").checked).toBe(true);
  });

  it("answers each of the three questions from its own scopes", async () => {
    renderRoom();

    file(/Which subscriptions quietly became more expensive/i);
    expect(
      await screen.findByText("Two raised their price without an email.")
    ).toBeInTheDocument();
    expect(screen.getByText("$11.99 → $15.49")).toBeInTheDocument();

    file(/What changed in my 30-day cash outlook/i);
    expect(
      await screen.findByText(/Tighter by \$180/i)
    ).toBeInTheDocument();
    expect(screen.getByText("$412.00")).toBeInTheDocument();
  });

  it("turns the apparatus over to show real mechanisms and their evidence", async () => {
    renderRoom();
    file(/Can I buy a \$600 flight/i);
    await screen.findByText("Yes — with $610.18 of room left.");

    // Consumer view speaks plainly and cites nothing.
    expect(screen.getByText(/Your data is read — and only read/i)).toBeInTheDocument();
    expect(screen.queryByText(/test_escalation_blocked/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Engineering proof/i }));

    // The same stations now state what the code actually does.
    expect(screen.getByText(/A capability can narrow, never widen/i)).toBeInTheDocument();
    expect(screen.getByText(/it opens a read-only one that always rolls back/i)).toBeInTheDocument();
    expect(screen.getByText(/test_escalation_blocked/)).toBeInTheDocument();
    expect(screen.getByText(/test_db_doors_are_exactly_the_sanctioned_set/)).toBeInTheDocument();
    // The tools actually called are named — in the tool list and on the receipt.
    expect(screen.getByText("get_accounts")).toBeInTheDocument();
    expect(screen.getAllByText("run_what_if")).toHaveLength(2);
  });

  it("never implies an agent can move money on its own", async () => {
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: /Engineering proof/i }));

    expect(screen.getByText("The only write is a proposal.")).toBeInTheDocument();
    expect(screen.getByText(/Executing it is a tap you make, in the app/i)).toBeInTheDocument();
    expect(screen.getByText(/the door is off unless you turn it on/i)).toBeInTheDocument();
  });

  it("offers every scope the MCP surface accepts, and no write scope", () => {
    renderRoom();
    for (const id of [
      "read:accounts",
      "read:transactions",
      "read:budgets",
      "read:goals",
      "read:forecast",
      "read:networth",
      "read:subscriptions",
      "read:scenarios",
      "read:context",
    ]) {
      expect(screen.getByText(id)).toBeInTheDocument();
    }
    expect(screen.queryByText("propose:actions")).not.toBeInTheDocument();
  });

  it("animates the passage when motion is welcome, and settles either way", async () => {
    setReducedMotion(false);
    renderRoom();
    file(/Which subscriptions quietly became more expensive/i);

    // With motion, the request is still in transit on the first frame…
    expect(screen.getByText(/Carrying the request/i)).toBeInTheDocument();
    // …and arrives under its own steam.
    await waitFor(
      () =>
        expect(
          screen.getByText("Two raised their price without an email.")
        ).toBeInTheDocument(),
      { timeout: 5000 }
    );
  });
});
