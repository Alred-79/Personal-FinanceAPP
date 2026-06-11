import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { post: (...a: unknown[]) => post(...a) } }));

import { useStore } from "@/store/store";

describe("store.scanReceipt", () => {
  // Braced body: returning the spy from beforeEach registers it as a vitest
  // cleanup callback, which then gets invoked (and awaited) after each test.
  beforeEach(() => {
    post.mockReset();
  });

  it("posts the file as multipart to /receipts/scan and returns the draft", async () => {
    const draft = { merchant: "Target", amount: 42.17, category: "Shops" };
    post.mockResolvedValue({ data: draft });

    const file = new File([new Uint8Array(8)], "r.png", { type: "image/png" });
    const result = await useStore.getState().scanReceipt(file);

    expect(result).toEqual(draft);
    expect(post).toHaveBeenCalledTimes(1);
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe("/receipts/scan");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBe(file);
    expect(config).toMatchObject({
      headers: { "Content-Type": "multipart/form-data" },
    });
  });

  it("propagates errors to the caller", async () => {
    post.mockImplementation(() => Promise.reject(new Error("502")));
    const file = new File([new Uint8Array(8)], "r.png", { type: "image/png" });

    let caught: unknown;
    try {
      await useStore.getState().scanReceipt(file);
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("502");
  });
});
