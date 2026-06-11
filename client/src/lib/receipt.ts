import { CATEGORIES } from "./colors";

/**
 * Client-side receipt upload guards. These mirror the server limits in
 * `receipt_service.py` so the user gets instant feedback, but the backend
 * remains the source of truth (it re-validates type and size).
 */
export const MAX_RECEIPT_BYTES = 5 * 1024 * 1024; // 5 MB

export const ALLOWED_RECEIPT_TYPES = [
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/webp",
] as const;

/**
 * Validate a chosen receipt file. Returns an error message to show the user,
 * or `null` when the file is acceptable.
 */
export function validateReceiptFile(file: File): string | null {
  if (!ALLOWED_RECEIPT_TYPES.includes(file.type as never)) {
    return "Unsupported file type. Upload a PNG, JPEG, or WebP image.";
  }
  if (file.size > MAX_RECEIPT_BYTES) {
    return "File too large. Maximum receipt size is 5 MB.";
  }
  if (file.size === 0) {
    return "That file looks empty. Pick a different image.";
  }
  return null;
}

const CANONICAL_BY_LOWER = new Map(CATEGORIES.map((c) => [c.toLowerCase(), c]));

/**
 * Map a category string from a receipt draft onto one of the form's canonical
 * categories (case-insensitively). Returns "" when there's no match, leaving
 * the field for the user to choose.
 */
export function normalizeDraftCategory(raw?: string | null): string {
  if (!raw) return "";
  return CANONICAL_BY_LOWER.get(raw.trim().toLowerCase()) ?? "";
}
