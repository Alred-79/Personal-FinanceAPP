import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ConfirmCard's Approve POSTs through the axios api; spy on it.
const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: { post: apiPost } }));

vi.mock("@/hooks/useVoiceInput", () => ({
  useVoiceInput: () => ({
    supported: false,
    isRecording: false,
    isTranscribing: false,
    error: null,
    start: vi.fn(),
    stop: vi.fn(),
    cancel: vi.fn(),
  }),
}));

import { AssistantInterface } from "@/components/custom/AssistantInterface/AssistantInterface";

/** A ReadableStream that emits the given SSE frames then closes. */
function sseStream(frames: string[]) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
}

const PROPOSAL_FRAME =
  `event: proposal\n` +
  `data: ${JSON.stringify({
    action: "scenario_commit",
    scenario_id: 7,
    summary: "Commit scenario #7 as 'Raise'",
    confirm_token: "tok-xyz",
    diff: {
      ending_balance: 500,
      timeline: [
        { date: "2026-03-01", balance: 1000, change: 0, label: "" },
        { date: "2026-03-31", balance: 1500, change: 500, label: "" },
      ],
    },
  })}\n\n` +
  `event: done\ndata: {}\n\n`;

beforeEach(() => {
  apiPost.mockReset();
  apiPost.mockResolvedValue({ data: { result: { plan_id: 9 } } });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: sseStream([PROPOSAL_FRAME]),
    })
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

function open() {
  const { container } = render(
    <MemoryRouter>
      <AssistantInterface />
    </MemoryRouter>
  );
  // The launcher is an icon-only button (no accessible name); grab it by class.
  const trigger = container.querySelector(".assistant-button") as HTMLElement;
  fireEvent.click(trigger);
}

describe("AssistantInterface — proposal frame", () => {
  it("renders the inline proposal + ConfirmCard and Approve hits confirm", async () => {
    open();

    // Send a what-if question (use an example chip if visible, else the input).
    const input = await screen.findByPlaceholderText(/ask/i);
    fireEvent.change(input, { target: { value: "what if I get a $5k raise?" } });
    fireEvent.keyDown(input, { key: "Enter" });

    // The proposal card renders from the streamed frame.
    await waitFor(() =>
      expect(screen.getByTestId("assistant-proposal")).toBeInTheDocument()
    );
    expect(screen.getByText(/Commit scenario #7/)).toBeInTheDocument();

    // Approve POSTs the token to the confirm endpoint.
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/assistant/actions/confirm/", {
        token: "tok-xyz",
      })
    );
  });
});
