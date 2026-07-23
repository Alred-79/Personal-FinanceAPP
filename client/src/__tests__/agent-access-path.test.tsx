import { describe, it, expect } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/**
 * The developer-connection path: a signed-out visitor lands on login carrying
 * a destination, and arrives at the AI connections settings area. These two
 * hops are easy to break silently, so they're pinned here.
 */

const { apiGet, apiPost } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: apiGet, post: apiPost, delete: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/hooks/useToast", () => ({ useToast: () => ({ toast: vi.fn() }), toast: vi.fn() }));

import Settings from "@/pages/Settings/Settings";

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
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
    apiGet.mockResolvedValue({ data: { enabled: true } });
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
  });
});
