import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";

const { apiGet, apiPost, apiDelete, toastSpy } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  toastSpy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: apiGet, post: apiPost, delete: apiDelete },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import { AgentKeys } from "@/components/custom/AgentKeys/AgentKeys";

const KEY = {
  id: 1,
  name: "Claude Desktop",
  key_prefix: "bdgt_live_ab",
  scopes: "read:accounts,read:transactions",
  created_at: "2026-06-01T00:00:00Z",
  last_used_at: null,
  expires_at: null,
  revoked: false,
};

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiDelete.mockReset();
  toastSpy.mockReset();
});
afterEach(cleanup);

describe("AgentKeys", () => {
  it("lists issued keys with their status and scopes", async () => {
    apiGet.mockResolvedValue({ data: [KEY] });
    render(<AgentKeys />);
    expect(await screen.findByText("Claude Desktop")).toBeInTheDocument();
    expect(screen.getByText("In Force")).toBeInTheDocument();
    // scope chips drop the read: prefix
    expect(screen.getByText("accounts")).toBeInTheDocument();
    expect(screen.getByText("transactions")).toBeInTheDocument();
  });

  it("shows the empty register when there are no keys", async () => {
    apiGet.mockResolvedValue({ data: [] });
    render(<AgentKeys />);
    expect(await screen.findByText("No writs on file")).toBeInTheDocument();
  });

  it("issues a key and reveals the raw secret exactly once", async () => {
    apiGet.mockResolvedValue({ data: [] });
    apiPost.mockResolvedValue({
      data: {
        raw_key: "bdgt_live_THE_SECRET_VALUE",
        id: 9,
        name: "My Agent",
        key_prefix: "bdgt_live_TH",
        scopes: "read:accounts,read:transactions",
        expires_at: null,
      },
    });
    render(<AgentKeys />);
    await screen.findByText("No writs on file");

    fireEvent.change(screen.getByPlaceholderText("e.g. Claude Desktop"), {
      target: { value: "My Agent" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Seal & Issue/i }));

    // The one-time reveal shows the raw key.
    expect(await screen.findByText("bdgt_live_THE_SECRET_VALUE")).toBeInTheDocument();
    expect(screen.getByText("Shown Once")).toBeInTheDocument();
    // It was POSTed with the default scopes.
    expect(apiPost).toHaveBeenCalledWith(
      "/mcp-keys/",
      expect.objectContaining({
        name: "My Agent",
        scopes: expect.arrayContaining(["read:accounts", "read:transactions"]),
      })
    );
  });

  it("revokes a live key", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiGet.mockResolvedValue({ data: [KEY] });
    apiDelete.mockResolvedValue({ data: { revoked: true, id: 1 } });
    render(<AgentKeys />);
    await screen.findByText("Claude Desktop");
    fireEvent.click(screen.getByRole("button", { name: /Void/i }));
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith("/mcp-keys/1/"));
  });
});
