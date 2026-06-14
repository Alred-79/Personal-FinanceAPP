import { CATEGORIES } from "./colors";

/**
 * Client-side guards for the Reconciliation Desk / Import Anything uploads.
 * These mirror the server limits in `routers/imports.py` (`import_max_bytes`,
 * the allowed types) so the user gets instant feedback, but the backend stays
 * the source of truth (it re-validates type and size).
 */
export const MAX_IMPORT_BYTES = 15 * 1024 * 1024; // 15 MB — statements run long

/** Document types the vision path accepts. CSV/plain text use the paste box. */
export const ALLOWED_IMPORT_TYPES = [
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/webp",
  "application/pdf",
] as const;

/**
 * Validate a chosen statement/document file. Returns an error message to show
 * the user, or `null` when the file is acceptable.
 */
export function validateImportFile(file: File): string | null {
  if (!ALLOWED_IMPORT_TYPES.includes(file.type as never)) {
    return "Unsupported file type. Upload a PNG, JPEG, WebP, or PDF.";
  }
  if (file.size > MAX_IMPORT_BYTES) {
    return "File too large. Maximum statement size is 15 MB.";
  }
  if (file.size === 0) {
    return "That file looks empty. Pick a different file.";
  }
  return null;
}

const CANONICAL_BY_LOWER = new Map(CATEGORIES.map((c) => [c.toLowerCase(), c]));

/**
 * Map an extracted category string onto one of the app's canonical categories
 * (case-insensitively). Returns the original trimmed value when there's no
 * canonical match, so a user's custom label is preserved.
 */
export function normalizeImportCategory(raw?: string | null): string {
  if (!raw) return "Other";
  const trimmed = raw.trim();
  return CANONICAL_BY_LOWER.get(trimmed.toLowerCase()) ?? trimmed;
}

/** Human label + tone for a row status, used by the review badges. */
export function statusLabel(status: string): { label: string; tone: "ok" | "warn" | "dup" } {
  switch (status) {
    case "duplicate":
      return { label: "Duplicate", tone: "dup" };
    case "exception":
      return { label: "Needs review", tone: "warn" };
    case "needs_category":
      return { label: "Pick category", tone: "warn" };
    case "transfer_candidate":
      return { label: "Transfer?", tone: "warn" };
    default:
      return { label: "Ready", tone: "ok" };
  }
}
