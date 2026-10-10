import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

/**
 * The landing's "Try the demo" lands on /login?demo=1. When the showcase is
 * ready that opens it directly; otherwise the normal sign-in page stays put.
 */

const { apiGet, bootstrap } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  bootstrap: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: apiGet, post: vi.fn(), delete: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  toast: vi.fn(),
}));

import Login from "@/pages/Login/Login";
import { useStore } from "@/store/store";

function demoStatus(ready: boolean) {
  apiGet.mockImplementation((url: string) =>
    Promise.resolve({
      data: url === "/demo-status" ? { enabled: true, ready } : { registration_open: false },
    })
  );
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<div data-testid="overview" />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  apiGet.mockReset();
  bootstrap.mockReset();
  bootstrap.mockResolvedValue(undefined);
  useStore.setState({ bootstrapDemoSession: bootstrap });
});
afterEach(cleanup);

describe("entering the demo from the landing", () => {
  it("opens the showcase straight away when it is ready", async () => {
    demoStatus(true);
    renderAt("/login?demo=1");
    await waitFor(() => expect(screen.getByTestId("overview")).toBeInTheDocument());
    expect(bootstrap).toHaveBeenCalledTimes(1);
  });

  it("waits on the normal page when the showcase is still being prepared", async () => {
    demoStatus(false);
    renderAt("/login?demo=1");
    expect(await screen.findByText(/The demo data is being prepared/i)).toBeInTheDocument();
    expect(bootstrap).not.toHaveBeenCalled();
  });

  it("does nothing special without the parameter", async () => {
    demoStatus(true);
    renderAt("/login");
    expect(await screen.findByRole("button", { name: /View demo data/i })).toBeInTheDocument();
    expect(bootstrap).not.toHaveBeenCalled();
  });
});
