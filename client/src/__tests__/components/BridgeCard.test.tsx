import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: { post: apiPost } }));

import BridgeCard from "@/components/custom/BridgeCard/BridgeCard";
import type { AssistantBridge } from "@/types";

const BRIDGE: AssistantBridge = {
  action: "propose_assisted_action",
  summary: "Set up a transfer of $340.00 from Checking to Savings",
  confirm_token: "bridge-tok",
  bridge: {
    kind: "transfer",
    amount: 340,
    rationale: "House goal is $340 short of this month's target.",
    source_ref: "Checking",
    dest_ref: "Savings",
    how: { instruction: "At your bank: transfer $340.00 from Checking to Savings." },
  },
};

beforeEach(() => {
  apiPost.mockReset();
  apiPost.mockResolvedValue({ data: { result: { assisted_action_id: 7 } } });
});
afterEach(() => cleanup());

describe("BridgeCard", () => {
  it("renders amount, source→dest, the why, and the instruction", () => {
    render(<BridgeCard bridge={BRIDGE} onDismiss={() => {}} />);
    expect(screen.getByText("$340.00")).toBeInTheDocument();
    expect(screen.getByText("Checking")).toBeInTheDocument();
    expect(screen.getByText("Savings")).toBeInTheDocument();
    expect(
      screen.getByText(/House goal is \$340 short/)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/At your bank: transfer \$340\.00/)
    ).toBeInTheDocument();
  });

  it("'Set this up' creates the Bridge via the confirm token, then shows the two-tap flow", async () => {
    render(<BridgeCard bridge={BRIDGE} onDismiss={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Set this up" }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/assistant/actions/confirm/", {
        token: "bridge-tok",
      })
    );
    // After recording, the execute affordances appear.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Do it in my bank" })
      ).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: "I did it" })).toBeInTheDocument();
  });

  it("'I did it' marks the Bridge done (provisional) on the router", async () => {
    render(<BridgeCard bridge={BRIDGE} onDismiss={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Set this up" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "I did it" })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: "I did it" }));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/assisted-actions/7/done/")
    );
    await waitFor(() =>
      expect(screen.getByText(/confirm it on your next bank sync/)).toBeInTheDocument()
    );
  });

  it("'Not now' dismisses without recording", () => {
    const onDismiss = vi.fn();
    render(<BridgeCard bridge={BRIDGE} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(apiPost).not.toHaveBeenCalled();
    expect(onDismiss).toHaveBeenCalled();
  });
});
