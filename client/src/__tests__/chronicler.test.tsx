/**
 * v4 package 07 — the Chronicler (client).
 *
 * The drawer header carries the AI label in every mode; the saga chapter ends in
 * exactly one action block; the chapter surface renders only what the engine
 * sent (the body has no stray digits in the fixture). Off-mode hides the chapter.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { type ReactNode } from "react";

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPut = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
    put: (...a: unknown[]) => apiPut(...a),
  },
}));

import { GameModeProvider, useGameMode } from "@/store/gameMode";
import { SagaChapter } from "@/components/custom/SagaChapter/SagaChapter";
import { ChroniclerDrawer } from "@/components/custom/ChroniclerDrawer/ChroniclerDrawer";

const CHAPTER = {
  title: "A Week in the Ledger",
  body: "The Keeper kept the watch and the standing debt gave ground. Quiet, durable work.",
  archetype_key: "quiet_builder",
  action: { kind: "confirm_forecast", label: "Confirm the forecast", deep_link: "/forecast" },
};

function mockMode(mode: string, chapter: unknown = CHAPTER) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/settings/") return Promise.resolve({ data: { preferences: { game_mode: mode } } });
    if (url === "/game/chapter/") return Promise.resolve({ data: { chapter } });
    return Promise.resolve({ data: {} });
  });
}

function AfterMode({ expect: want, children }: { expect: string; children: ReactNode }) {
  const { mode } = useGameMode();
  if (want !== "off" && mode !== want) return null;
  return <>{children}</>;
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPut.mockReset();
  document.documentElement.dataset.mode = "off";
});
afterEach(() => cleanup());

describe("saga chapter", () => {
  it("renders exactly one action block, hidden in off mode", async () => {
    mockMode("off");
    const off = render(
      <GameModeProvider><MemoryRouter><SagaChapter /></MemoryRouter></GameModeProvider>
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/settings/"));
    expect(off.queryByTestId("saga-chapter")).not.toBeInTheDocument();
    off.unmount();

    mockMode("full");
    const { findByTestId, getAllByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="full"><SagaChapter /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    await findByTestId("saga-chapter");
    expect(getAllByTestId("chapter-action")).toHaveLength(1);
  });

  it("the chapter body carries no stray digits", async () => {
    mockMode("ambient");
    const { findByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="ambient"><SagaChapter /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    const body = await findByTestId("chapter-body");
    expect(body.textContent || "").not.toMatch(/[0-9]/);
  });
});

describe("chronicler drawer", () => {
  it("shows the AI label in every mode", async () => {
    for (const mode of ["off", "ambient", "full"]) {
      mockMode(mode);
      // Force the drawer open by dispatching the `/` key, then assert the label.
      const { findByTestId, unmount } = render(
        <GameModeProvider>
          <MemoryRouter>
            <AfterMode expect={mode}><ChroniclerDrawer defaultOpen /></AfterMode>
          </MemoryRouter>
        </GameModeProvider>
      );
      const label = await findByTestId("ai-label");
      expect(label.textContent).toBe("AI");
      unmount();
      cleanup();
    }
  });
});
