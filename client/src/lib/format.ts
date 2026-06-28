// Keyed by the canonical category names (client/src/lib/colors.ts ·
// server CANONICAL_CATEGORIES) so every real category gets a stable color
// instead of falling through to the hash picker below. Truly custom user
// labels still hash into FALLBACK_COLORS.
const CATEGORY_COLORS: Record<string, string> = {
  Housing:          "hsl(150, 100%, 50%)", // green
  Food:             "hsl(150, 100%, 50%)", // green
  "Food and Drink": "hsl(160, 85%, 45%)",  // emerald
  Transportation:   "hsl(46, 100%, 50%)",  // yellow
  Utilities:        "hsl(25, 100%, 55%)",  // orange
  Entertainment:    "hsl(185, 100%, 50%)", // cyan
  Work:             "hsl(150, 100%, 50%)", // green (income)
  Service:          "hsl(210, 16%, 52%)",  // steel — neutral services umbrella
  Shops:            "hsl(290, 100%, 65%)", // purple
  Transfer:         "hsl(215, 20%, 55%)",  // slate
  Travel:           "hsl(212, 90%, 58%)",  // blue
  Health:           "hsl(3, 100%, 60%)",   // red
  Fitness:          "hsl(262, 80%, 62%)",  // violet
  Other:            "hsl(0, 0%, 60%)",     // gray
  // Back-compat aliases for older stored labels / Plaid synonyms.
  Transport:        "hsl(46, 100%, 50%)",
  Shopping:         "hsl(290, 100%, 65%)",
  Income:           "hsl(150, 100%, 50%)",
};

const FALLBACK_COLORS = Object.values(CATEGORY_COLORS);

export function categoryColor(category: string, fallback?: string): string {
  if (CATEGORY_COLORS[category]) return CATEGORY_COLORS[category];
  let hash = 0;
  for (let i = 0; i < category.length; i++) {
    hash = (hash * 31 + category.charCodeAt(i)) >>> 0;
  }
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length] ?? fallback ?? "hsl(150, 100%, 50%)";
}

export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}
