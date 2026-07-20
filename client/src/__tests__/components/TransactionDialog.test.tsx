import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
  act,
} from "@testing-library/react";

// Hoisted so the vi.mock factories (which are themselves hoisted) can close
// over these spies.
const { fetchAccounts, toastSpy } = vi.hoisted(() => ({
  fetchAccounts: vi.fn(),
  toastSpy: vi.fn(),
}));

// The dialog reads accounts from the store and fires accounts fetch on open.
vi.mock("@/store/store", () => ({
  useStore: () => ({
    accounts: [{ id: 7, name: "Checking", balance: 100, type: "checking" }],
    fetchAccounts,
  }),
}));

// Spy on the toast helper so we can assert a failure surfaces one.
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

// Radix Select is intractable to drive in jsdom (pointer capture, scrollIntoView,
// portal/keyboard quirks). Replace it with deterministic native-element shims so
// this test exercises the DIALOG's submit/error logic — the thing under test —
// not radix internals. The shims preserve the value/onValueChange contract.
vi.mock("@/components/ui/select", () => {
  const Ctx = React.createContext<{
    value?: string;
    onValueChange?: (v: string) => void;
  }>({});
  const Select = ({
    value,
    onValueChange,
    children,
  }: {
    value?: string;
    onValueChange?: (v: string) => void;
    children: React.ReactNode;
  }) =>
    React.createElement(Ctx.Provider, { value: { value, onValueChange } }, children);
  const SelectTrigger = ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children);
  const SelectValue = ({ placeholder }: { placeholder?: string }) => {
    const { value } = React.useContext(Ctx);
    return React.createElement("span", null, value || placeholder);
  };
  const SelectContent = ({ children }: { children: React.ReactNode }) => {
    const { onValueChange } = React.useContext(Ctx);
    // Render each item as a button so a test can click it deterministically.
    return React.createElement(
      "div",
      { role: "listbox" },
      React.Children.map(children, (child) => {
        const el = child as React.ReactElement<{ value: string; children: React.ReactNode }>;
        return el
          ? React.createElement(
              "button",
              {
                type: "button",
                role: "option",
                onClick: () => onValueChange?.(el.props.value),
              },
              el.props.children
            )
          : null;
      })
    );
  };
  const SelectItem = ({ children }: { value: string; children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children);
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

import { TransactionDialog } from "@/components/custom/TransactionDialog/TransactionDialog";

beforeEach(() => {
  fetchAccounts.mockReset();
  toastSpy.mockReset();
});
afterEach(() => cleanup());

/** Fill the required fields so the form is submittable, via the deterministic
 * Select shims (each option is a clickable role="option" button). */
function fillForm() {
  fireEvent.change(screen.getByLabelText("Title"), {
    target: { value: "Coffee" },
  });
  fireEvent.change(screen.getByLabelText("Amount"), {
    target: { value: "4.50" },
  });
  // There are three Selects (recurrence, account, category) — target by the
  // exact option label so we set the two REQUIRED ones (account + category)
  // and not the optional recurrence.
  fireEvent.click(
    screen
      .getAllByRole("option")
      .find((o) => /^Checking/.test(o.textContent ?? ""))!
  );
  fireEvent.click(
    screen
      .getAllByRole("option")
      .find((o) => o.textContent === "Housing")!
  );
}

describe("TransactionDialog failure handling", () => {
  it("keeps the dialog open, keeps the form populated, toasts, and re-enables the button when onSubmit rejects", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(new Error("server 500"));

    render(<TransactionDialog onSubmit={onSubmit} open onOpenChange={() => {}} />);

    await fillForm();

    const submit = screen.getByRole("button", { name: /add transaction/i });
    expect(submit).not.toBeDisabled();

    fireEvent.click(submit);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    // Failure path: a toast fired...
    await waitFor(() => expect(toastSpy).toHaveBeenCalled());
    const arg = toastSpy.mock.calls.at(-1)?.[0];
    expect(arg?.variant).toBe("destructive");

    // ...the form keeps its values (the entry isn't lost)...
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(
      "Coffee"
    );
    expect((screen.getByLabelText("Amount") as HTMLInputElement).value).toBe(
      "4.50"
    );

    // ...and the submit button re-enables for a retry.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /add transaction/i })
      ).not.toBeDisabled()
    );
  });

  it("closes and clears on a successful submit", async () => {
    const onOpenChange = vi.fn();
    const onSubmit = vi.fn().mockResolvedValue(undefined);

    render(
      <TransactionDialog onSubmit={onSubmit} open onOpenChange={onOpenChange} />
    );

    await fillForm();
    fireEvent.click(screen.getByRole("button", { name: /add transaction/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    // Success closes the dialog (onOpenChange(false)).
    await waitFor(() =>
      expect(onOpenChange).toHaveBeenCalledWith(false)
    );
    expect(toastSpy).not.toHaveBeenCalled();
  });

  it("guards against double-submit (a second click while in flight is ignored)", async () => {
    let resolve!: () => void;
    const onSubmit = vi.fn(
      () => new Promise<void>((r) => (resolve = r))
    );

    render(<TransactionDialog onSubmit={onSubmit} open onOpenChange={() => {}} />);
    await fillForm();

    const submit = screen.getByRole("button", { name: /saving|add transaction/i });
    fireEvent.click(submit);
    // While the first submit is pending, the button is disabled — a second
    // click can't fire another save.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /saving|add transaction/i })
      ).toBeDisabled()
    );
    fireEvent.click(
      screen.getByRole("button", { name: /saving|add transaction/i })
    );

    expect(onSubmit).toHaveBeenCalledTimes(1);
    // Resolve the pending submit inside act() so the post-success state update
    // (close + clear) is flushed without a React act() warning.
    await act(async () => {
      resolve();
    });
  });
});
