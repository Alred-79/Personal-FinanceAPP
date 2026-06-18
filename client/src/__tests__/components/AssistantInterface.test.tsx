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

// W2 — cite sources (verifiable AI). A token answer followed by a ``sources``
// frame shows "Based on N transactions" under the figure; expanding lists the
// cited rows. A pure-chat turn (no sources frame) shows no citation.
const SOURCES_STREAM = (frames: string[]) => sseStream(frames);

const TOKEN_FRAME = (text: string) =>
  `event: token\ndata: ${JSON.stringify(text)}\n\n`;

const SOURCES_FRAME = (body: unknown) =>
  `event: sources\ndata: ${JSON.stringify(body)}\n\n`;

const DONE_FRAME = `event: done\ndata: {}\n\n`;

describe("AssistantInterface — sources frame (W2)", () => {
  it("renders 'Based on N transactions' and expands to the cited rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: SOURCES_STREAM([
          TOKEN_FRAME("You spent $64.50 this week."),
          SOURCES_FRAME({
            data: [
              { id: 1, title: "Coffee", date: "2026-06-01", amount: 4.5 },
              { id: 2, title: "Groceries", date: "2026-06-02", amount: 60 },
            ],
            count: 2,
            total: 2,
            capped: false,
          }),
          DONE_FRAME,
        ]),
      })
    );
    open();
    const input = await screen.findByPlaceholderText(/ask/i);
    fireEvent.change(input, { target: { value: "how much did I spend?" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const cite = await screen.findByTestId("sources-citation");
    expect(cite).toHaveTextContent("Based on 2 transactions");

    // Rows are hidden until expanded.
    expect(screen.queryByTestId("sources-list")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Based on 2 transactions/ }));
    expect(screen.getByTestId("sources-list")).toBeInTheDocument();
    expect(screen.getByText("Coffee")).toBeInTheDocument();
    expect(screen.getByText("Groceries")).toBeInTheDocument();
  });

  it("labels 'N of M' when the read tool truncated its output", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: SOURCES_STREAM([
          TOKEN_FRAME("Here's a summary."),
          SOURCES_FRAME({
            data: [{ id: 1, title: "A", date: "2026-06-01", amount: 1 }],
            count: 1,
            total: 137,
            capped: true,
          }),
          DONE_FRAME,
        ]),
      })
    );
    open();
    const input = await screen.findByPlaceholderText(/ask/i);
    fireEvent.change(input, { target: { value: "show me everything" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const cite = await screen.findByTestId("sources-citation");
    expect(cite).toHaveTextContent("Based on 1 of 137 transactions");
  });

  it("shows no citation for a pure-chat turn (no sources frame)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: SOURCES_STREAM([TOKEN_FRAME("Hi there!"), DONE_FRAME]),
      })
    );
    open();
    const input = await screen.findByPlaceholderText(/ask/i);
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await screen.findByText("Hi there!");
    expect(screen.queryByTestId("sources-citation")).not.toBeInTheDocument();
  });
});
