import { describe, it, expect, vi, beforeEach } from "vitest";

// F1 — refreshOnce() must collapse concurrent callers onto ONE POST /refresh/.
// We mock the axios instance's post and drive refreshOnce concurrently.
const { apiPost, responseUse } = vi.hoisted(() => ({
  apiPost: vi.fn(),
  responseUse: vi.fn(),
}));

vi.mock("axios", () => {
  const instance = {
    post: apiPost,
    interceptors: {
      request: { use: vi.fn() },
      response: { use: responseUse },
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

  it("does not start a refresh loop when demo login itself is unauthorized", async () => {
    const rejectResponse = responseUse.mock.calls[0][1] as (
      error: unknown
    ) => Promise<unknown>;
    const error = {
      config: { url: "/demo-login/" },
      response: { status: 401 },
    };

    await expect(rejectResponse(error)).rejects.toBe(error);
    expect(apiPost).not.toHaveBeenCalled();
  });
});
