export const chartColors = {
  primary:   "hsl(150, 100%, 50%)",
  secondary: "hsl(46, 100%, 50%)",
  cyan:      "hsl(185, 100%, 50%)",
  red:       "hsl(3, 100%, 60%)",
  purple:    "hsl(290, 100%, 65%)",
  orange:    "hsl(25, 100%, 55%)",
} as const;

/**
 * Canonical transaction categories. Mirrors the server's
 * ``CANONICAL_CATEGORIES`` (categorization_service.py) so that values produced
 * by the backend (Plaid sync, receipt OCR, auto-categorization) always line up
 * with the options offered in the transaction form.
 */
export const CATEGORIES = [
  "Housing",
  "Food",
  "Transportation",
  "Utilities",
  "Entertainment",
  "Work",
  "Food and Drink",
  "Service",
  "Shops",
  "Transfer",
  "Travel",
  "Other",
] as const;

export type Category = (typeof CATEGORIES)[number];

// A color per canonical category, drawn from the Terminal Ledger palette so
// category chips/badges stay on-theme. Cycles through the chart hues.
const PALETTE = Object.values(chartColors);
export const categoryColors: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((cat, i) => [cat, PALETTE[i % PALETTE.length]])
);
