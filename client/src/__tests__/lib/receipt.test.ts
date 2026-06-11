import { describe, it, expect } from "vitest";
import {
  validateReceiptFile,
  normalizeDraftCategory,
  MAX_RECEIPT_BYTES,
} from "@/lib/receipt";

const fileOfSize = (bytes: number, type: string, name = "r") =>
  new File([new Uint8Array(bytes)], name, { type });

describe("validateReceiptFile", () => {
  it("accepts a normal PNG", () => {
    expect(validateReceiptFile(fileOfSize(1024, "image/png"))).toBeNull();
  });

  it("accepts JPEG and WebP", () => {
    expect(validateReceiptFile(fileOfSize(1024, "image/jpeg"))).toBeNull();
    expect(validateReceiptFile(fileOfSize(1024, "image/webp"))).toBeNull();
  });

  it("rejects an unsupported type", () => {
    expect(validateReceiptFile(fileOfSize(1024, "application/pdf"))).toMatch(
      /Unsupported file type/
    );
  });

  it("rejects files over 5 MB", () => {
    expect(
      validateReceiptFile(fileOfSize(MAX_RECEIPT_BYTES + 1, "image/png"))
    ).toMatch(/too large/i);
  });

  it("rejects an empty file", () => {
    expect(validateReceiptFile(fileOfSize(0, "image/png"))).toMatch(/empty/i);
  });
});

describe("normalizeDraftCategory", () => {
  it("passes through an exact canonical category", () => {
    expect(normalizeDraftCategory("Shops")).toBe("Shops");
  });

  it("matches case-insensitively", () => {
    expect(normalizeDraftCategory("food and drink")).toBe("Food and Drink");
    expect(normalizeDraftCategory("  TRANSPORTATION ")).toBe("Transportation");
  });

  it("returns '' for unknown categories", () => {
    expect(normalizeDraftCategory("Groceries")).toBe("");
  });

  it("returns '' for null/empty input", () => {
    expect(normalizeDraftCategory(null)).toBe("");
    expect(normalizeDraftCategory(undefined)).toBe("");
    expect(normalizeDraftCategory("")).toBe("");
  });
});
