/**
 * Engraver's chart inks. These reference CSS variables so charts re-ink when
 * the theme flips between Ledger Paper and Midnight Vault. `track` is the
 * hairline ruling colour used for chart gridlines.
 */
export const chartColors = {
  primary:   "hsl(var(--credit))",
  secondary: "hsl(var(--gold))",
  cyan:      "hsl(var(--chart-3))",
  red:       "hsl(var(--debit))",
  purple:    "hsl(var(--chart-5))",
  orange:    "hsl(var(--chart-6))",
  track:     "hsl(var(--rule) / 0.6)",
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
  "Health",
  "Fitness",
  "Other",
] as const;

export type Category = (typeof CATEGORIES)[number];

// A color per canonical category, drawn from the Terminal Ledger palette so
// category chips/badges stay on-theme. Cycles through the chart hues.
const PALETTE = Object.values(chartColors);
export const categoryColors: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((cat, i) => [cat, PALETTE[i % PALETTE.length]])
);
