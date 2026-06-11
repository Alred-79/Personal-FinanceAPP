import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const toast = vi.fn();
vi.mock("@/hooks/useToast", () => ({ useToast: () => ({ toast }) }));

const scanReceipt = vi.fn();
vi.mock("@/store/store", () => ({
  useStore: (selector: (s: { scanReceipt: typeof scanReceipt }) => unknown) =>
    selector({ scanReceipt }),
}));

import { ReceiptDropzone } from "@/components/custom/TransactionDialog/ReceiptDropzone";

const pngFile = () =>
  new File([new Uint8Array(16)], "receipt.png", { type: "image/png" });

const selectFile = (file: File) => {
  const input = document.querySelector(
    'input[type="file"]'
  ) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
};

describe("ReceiptDropzone", () => {
  beforeEach(() => {
    toast.mockReset();
    scanReceipt.mockReset();
  });

  it("calls onScanned with the extracted draft on success", async () => {
    const draft = { merchant: "Target", amount: 42.17, category: "Shops" };
    scanReceipt.mockResolvedValue(draft);
    const onScanned = vi.fn();

    render(<ReceiptDropzone onScanned={onScanned} />);
    selectFile(pngFile());

    await waitFor(() => expect(onScanned).toHaveBeenCalledWith(draft));
    expect(scanReceipt).toHaveBeenCalledTimes(1);
  });

  it("toasts and does not call onScanned when scanning fails", async () => {
    scanReceipt.mockRejectedValue({
      response: { data: { detail: "Could not read the receipt." } },
    });
    const onScanned = vi.fn();

    render(<ReceiptDropzone onScanned={onScanned} />);
    selectFile(pngFile());

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: "destructive" })
      )
    );
    expect(onScanned).not.toHaveBeenCalled();
  });

  it("rejects an unsupported file client-side without scanning", async () => {
    const onScanned = vi.fn();
    render(<ReceiptDropzone onScanned={onScanned} />);

    selectFile(new File(["x"], "notes.txt", { type: "text/plain" }));

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(scanReceipt).not.toHaveBeenCalled();
    expect(onScanned).not.toHaveBeenCalled();
  });
});
