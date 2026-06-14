import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: { post: apiPost } }));

import ConfirmCard from "@/components/custom/ConfirmCard/ConfirmCard";

beforeEach(() => {
  apiPost.mockReset();
  apiPost.mockResolvedValue({ data: { result: { plan_id: 5 } } });
});
afterEach(() => cleanup());

describe("ConfirmCard", () => {
  it("renders the summary and both actions", () => {
    render(<ConfirmCard summary="Commit scenario #3" token="tok" />);
    expect(screen.getByText("Commit scenario #3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Decline" })).toBeInTheDocument();
  });

  it("Approve POSTs the token to confirm and shows an approved seal", async () => {
    const onConfirmed = vi.fn();
    render(
      <ConfirmCard summary="Commit scenario #3" token="tok-abc" onConfirmed={onConfirmed} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/assistant/actions/confirm/", {
        token: "tok-abc",
      })
    );
    expect(onConfirmed).toHaveBeenCalledWith({ plan_id: 5 });
    await waitFor(() => expect(screen.getByText("Done.")).toBeInTheDocument());
  });

  it("Decline dismisses the card without a POST", () => {
    const onDecline = vi.fn();
    const { container } = render(
      <ConfirmCard summary="X" token="tok" onDecline={onDecline} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(apiPost).not.toHaveBeenCalled();
    expect(onDecline).toHaveBeenCalled();
    // The card removes itself on decline.
    expect(container.querySelector('[data-testid="confirm-card"]')).toBeNull();
  });
});
