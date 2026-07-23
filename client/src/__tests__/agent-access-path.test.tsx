import { describe, it, expect } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/**
 * The developer-connection path: a signed-out visitor lands on login carrying
 * a destination, and arrives at the AI connections settings area. These two
 * hops are easy to break silently, so they're pinned here.
 */

const { apiGet, apiPost, toastSpy } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  toastSpy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: apiGet, post: apiPost, delete: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import Settings from "@/pages/Settings/Settings";
import { useStore } from "@/store/store";

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  toastSpy.mockReset();
  apiGet.mockResolvedValue({ data: {} });
});
afterEach(cleanup);

/** Renders whatever the router currently points at, for redirect assertions. */
function Here() {
  const loc = useLocation();
  return <div data-testid="here">{loc.pathname + loc.search}</div>;
}

describe("the agent-access path", () => {
  it("opens Settings on the Agent Keys folio when the tab is named", async () => {
    render(
      <MemoryRouter initialEntries={["/settings?tab=agent-keys"]}>
        <Routes>
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    );
    // The connection area's own heading, not merely the tab trigger.
    expect(
      await screen.findByRole("heading", { name: "Claude Code / developer connection" })
    ).toBeInTheDocument();
  });

  it("opens the default folio when no tab is named", async () => {
    render(
      <MemoryRouter initialEntries={["/settings"]}>
        <Routes>
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByText(/Thresholds/i)).toBeInTheDocument();
    expect(screen.queryByText(/Claude Code \/ developer connection/i)).not.toBeInTheDocument();
  });

  it("ignores a tab name that isn't a folio", async () => {
    render(
      <MemoryRouter initialEntries={["/settings?tab=../../etc/passwd"]}>
        <Routes>
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByText(/Thresholds/i)).toBeInTheDocument();
  });

  it("returns the visitor to ?next= after signing in", async () => {
    apiPost.mockResolvedValue({ data: {} });
    const { default: Login } = await import("@/pages/Login/Login");
    const { fireEvent, waitFor } = await import("@testing-library/react");

    render(
      <MemoryRouter initialEntries={["/login?next=%2Fsettings%3Ftab%3Dagent-keys"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/settings" element={<Here />} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "u" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "p" } });
    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() =>
      expect(screen.getByTestId("here")).toHaveTextContent("/settings?tab=agent-keys")
    );
  });

  it("clears a prior demo user's data before entering a normal session", async () => {
    useStore.setState({
      user: {
        id: 7,
        username: "demo",
        full_name: "Jordan Rivera",
        is_demo: true,
      },
      userLoaded: true,
      isLoggedIn: true,
      isDemoSession: true,
      safeToSpend: { available: 999 } as never,
      budgets: [{ id: 44 }] as never,
      budgetsLoaded: true,
      accounts: [{ id: 55 }] as never,
      accountsLoaded: true,
      settingsLoaded: true,
      mcpEnabled: true,
      linkToken: "demo-link-token",
    });
    apiPost.mockResolvedValue({ data: {} });
    const { default: Login } = await import("@/pages/Login/Login");
    const { fireEvent, waitFor } = await import("@testing-library/react");

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Here />} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "maya" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct horse" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() => expect(screen.getByTestId("here")).toHaveTextContent("/"));
    expect(useStore.getState()).toMatchObject({
      user: null,
      userLoaded: false,
      isLoggedIn: true,
      isDemoSession: false,
      safeToSpend: null,
      budgets: [],
      budgetsLoaded: false,
      accounts: [],
      accountsLoaded: false,
      settingsLoaded: false,
      mcpEnabled: false,
      linkToken: null,
    });
    expect(apiPost).not.toHaveBeenCalledWith("/logout/");
  });

  it("refuses to bounce a signed-in visitor off-site", async () => {
    apiPost.mockResolvedValue({ data: {} });
    const { default: Login } = await import("@/pages/Login/Login");
    const { fireEvent, waitFor } = await import("@testing-library/react");

    render(
      <MemoryRouter initialEntries={["/login?next=//evil.example.com/steal"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Here />} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "u" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "p" } });
    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    // Protocol-relative targets are not internal paths — fall back to the dashboard.
    await waitFor(() => expect(screen.getByTestId("here")).toHaveTextContent("/"));
    expect(screen.getByTestId("here")).not.toHaveTextContent("evil.example.com");
  });

  it("opens the pre-filled showcase from the one-tap demo entry", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/demo-status") {
        return Promise.resolve({ data: { enabled: true, ready: true } });
      }
      if (url === "/users/me/") {
        return Promise.resolve({
          data: {
            id: 7,
            username: "demo",
            full_name: "Jordan Rivera",
            is_demo: true,
          },
        });
      }
      if (url === "/settings/") {
        return Promise.resolve({
          data: {
            preferences: {
              spend_warning: 70,
              savings_percent: 20,
              game_mode: "ambient",
            },
            features: { mcp_enabled: true },
          },
        });
      }
      if (url === "/spend/safe-to-spend") {
        return Promise.resolve({ data: { available: 842 } });
      }
      if (url === "/budgets") return Promise.resolve({ data: [{ id: 1 }] });
      if (url === "/transactions") {
        return Promise.resolve({
          data: {
            items: [
              {
                id: 1,
                title: "Groceries",
                category: "Food",
                amount: 64,
                date: "2026-07-22",
                type: "expense",
              },
            ],
            total: 1,
          },
        });
      }
      if (url === "/networth") {
        return Promise.resolve({ data: [{ date: "2026-07-22", total: 24_500 }] });
      }
      if (url === "/forecast") {
        return Promise.resolve({
          data: {
            horizon_start: "2026-07-23",
            timeline: [{ date: "2026-07-23", balance: 4200 }],
            events: [],
          },
        });
      }
      if (url === "/accounts") {
        return Promise.resolve({
          data: [{ id: 1, name: "Everyday Checking", type: "checking", balance: 4200 }],
        });
      }
      if (url === "/accounts/all/transactions") {
        return Promise.resolve({ data: { "1": [] } });
      }
      return Promise.resolve({ data: 100 });
    });
    apiPost.mockResolvedValue({ data: {} });
    const { default: Login } = await import("@/pages/Login/Login");
    const { fireEvent, waitFor } = await import("@testing-library/react");

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Here />} />
        </Routes>
      </MemoryRouter>
    );

    const demoButton = await screen.findByRole("button", { name: "View demo data" });
    expect(screen.getByText(/No sign-up or bank connection/i)).toBeInTheDocument();
    fireEvent.click(demoButton);

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/demo-login"));
    await waitFor(() => expect(screen.getByTestId("here")).toHaveTextContent("/"));
    expect(useStore.getState()).toMatchObject({
      isLoggedIn: true,
      isDemoSession: true,
      user: { username: "demo" },
      settingsLoaded: true,
      hasLoaded: true,
      budgetsLoaded: true,
      netWorthLoaded: true,
      forecastLoaded: true,
      accountsLoaded: true,
    });
  });

  it("shows a quiet retry state when demo mode is enabled but not ready", async () => {
    apiGet.mockResolvedValue({ data: { enabled: true, ready: false } });
    const { default: Login } = await import("@/pages/Login/Login");

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("The demo data is being prepared.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View demo data" })).not.toBeInTheDocument();
  });

  it("fails closed for an older enabled-only demo status response", async () => {
    apiGet.mockResolvedValue({ data: { enabled: true } });
    const { default: Login } = await import("@/pages/Login/Login");

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("The demo data is being prepared.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View demo data" })).not.toBeInTheDocument();
  });

  it("keeps a failed demo bootstrap on login with one calm inline message", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/demo-status") {
        return Promise.resolve({ data: { enabled: true, ready: true } });
      }
      return Promise.reject(new Error("temporarily unavailable"));
    });
    apiPost.mockResolvedValue({ data: {} });
    const { default: Login } = await import("@/pages/Login/Login");
    const { fireEvent } = await import("@testing-library/react");

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Here />} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole("button", { name: "View demo data" }));

    expect(
      await screen.findByText("The demo is being refreshed. Please try again in a moment.")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("here")).not.toBeInTheDocument();
    expect(toastSpy).not.toHaveBeenCalled();
    expect(useStore.getState().isLoggedIn).toBe(false);
    // A POST /demo-login succeeded before hydration failed, so the client also
    // clears the newly minted cookies instead of leaving a partial session.
    expect(apiPost).toHaveBeenCalledWith("/logout/");
  });
});
