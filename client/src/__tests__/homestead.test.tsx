/**
 * v4 package 09 — the Homestead (client).
 *
 * The reveal shows the projection hero + one commit action; the accrual line
 * renders ONLY when the server included the key (trivial-sum suppression — the
 * client never fabricates "$0.04"). Hidden in off mode.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { type ReactNode } from "react";

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => apiGet(...a), post: vi.fn(), put: vi.fn() },
}));

import { GameModeProvider, useGameMode } from "@/store/gameMode";
import { Homestead } from "@/components/custom/Homestead/Homestead";

function mockMode(mode: string, reveal: unknown) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/settings/") return Promise.resolve({ data: { preferences: { game_mode: mode } } });
    if (url === "/game/homestead/") return Promise.resolve({ data: { reveal } });
    return Promise.resolve({ data: {} });
  });
}

function AfterMode({ expect: want, children }: { expect: string; children: ReactNode }) {
  const { mode } = useGameMode();
  if (want !== "off" && mode !== want) return null;
  return <>{children}</>;
}

const REVEAL_NO_ACCRUAL = {
  projection_date: "2027-06-01",
  projection_cents: 500000,
  action: { kind: "what_if_commit", label: "Add $25/mo?", deep_link: "/forecast" },
  // accrual_cents intentionally ABSENT (suppressed below $1.00)
};
const REVEAL_WITH_ACCRUAL = { ...REVEAL_NO_ACCRUAL, accrual_cents: 150 };

beforeEach(() => {
  apiGet.mockReset();
  document.documentElement.dataset.mode = "off";
});
afterEach(() => cleanup());

describe("homestead reveal", () => {
  it("hides in off mode", async () => {
    mockMode("off", REVEAL_NO_ACCRUAL);
    const { queryByTestId } = render(
      <GameModeProvider><MemoryRouter><Homestead /></MemoryRouter></GameModeProvider>
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/settings/"));
    expect(queryByTestId("homestead")).not.toBeInTheDocument();
  });

  it("shows projection + one action, no accrual line when suppressed", async () => {
    mockMode("full", REVEAL_NO_ACCRUAL);
    const { findByTestId, queryByTestId } = render(
      <GameModeProvider>
        <MemoryRouter><AfterMode expect="full"><Homestead /></AfterMode></MemoryRouter>
      </GameModeProvider>
    );
    await findByTestId("homestead");
    expect(queryByTestId("homestead-projection")).toBeInTheDocument();
    expect(queryByTestId("homestead-action")).toBeInTheDocument();
    expect(queryByTestId("homestead-accrual")).not.toBeInTheDocument(); // suppressed
  });

  it("shows the accrual line only when the server sent it", async () => {
    mockMode("full", REVEAL_WITH_ACCRUAL);
    const { findByTestId } = render(
      <GameModeProvider>
        <MemoryRouter><AfterMode expect="full"><Homestead /></AfterMode></MemoryRouter>
      </GameModeProvider>
    );
    const accrual = await findByTestId("homestead-accrual");
    expect(accrual.textContent).toContain("$2"); // 150c → ~$2, never "$0.04"
  });
});
