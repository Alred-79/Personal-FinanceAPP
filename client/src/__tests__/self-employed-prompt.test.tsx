import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SelfEmployedFork } from "@/components/custom/Onboarding/SelfEmployedFork";
import { useStore } from "@/store/store";

describe("optional work-money personalization", () => {
  beforeEach(() => {
    localStorage.removeItem("self_employed");
    localStorage.removeItem("self_employed_prompt_dismissed");
    useStore.setState({
      isLoggedIn: true,
      settingsLoaded: true,
      selfEmployed: null,
      selfEmployedPromptDismissed: false,
    });
  });
  afterEach(cleanup);

  it("is non-modal and dismisses without changing employment status", () => {
    render(<SelfEmployedFork />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(useStore.getState().selfEmployed).toBeNull();
    expect(useStore.getState().selfEmployedPromptDismissed).toBe(true);
    expect(localStorage.getItem("self_employed_prompt_dismissed")).toBe("true");
  });
});
