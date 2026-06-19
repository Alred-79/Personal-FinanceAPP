import { describe, it, expect, vi, beforeEach } from "vitest";

// F1 — refreshOnce() must collapse concurrent callers onto ONE POST /refresh/.
// We mock the axios instance's post and drive refreshOnce concurrently.
const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));

vi.mock("axios", () => {
  const instance = {
    post: apiPost,
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };
  return { default: { create: () => instance } };
});

import { refreshOnce } from "@/lib/api";

describe("refreshOnce — single-flight refresh (F1)", () => {
  beforeEach(() => {
    apiPost.mockReset();
  });

  it("issues exactly one /refresh/ for many concurrent callers", async () => {
    let resolveRefresh: (v: unknown) => void = () => {};
    apiPost.mockImplementation(
      () => new Promise((res) => {
        resolveRefresh = res;
      })
    );

    // Fire five concurrent refreshes while the first is still in flight.
    const calls = [refreshOnce(), refreshOnce(), refreshOnce(), refreshOnce(), refreshOnce()];
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost).toHaveBeenCalledWith("/refresh/");

    resolveRefresh({});
    await Promise.all(calls);
  });

  it("allows a fresh refresh AFTER the first settles", async () => {
    apiPost.mockResolvedValue({});
    await refreshOnce();
    await refreshOnce();
    expect(apiPost).toHaveBeenCalledTimes(2); // the in-flight promise was cleared
  });

  it("propagates a refresh failure to the caller", async () => {
    apiPost.mockRejectedValueOnce(new Error("401"));
    await expect(refreshOnce()).rejects.toThrow("401");
    // And recovers: the next call can succeed.
    apiPost.mockResolvedValueOnce({});
    await expect(refreshOnce()).resolves.toBeUndefined();
  });
});
