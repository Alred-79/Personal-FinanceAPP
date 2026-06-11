const CATEGORY_COLORS: Record<string, string> = {
  Food:          "hsl(150, 100%, 50%)",
  Transport:     "hsl(46, 100%, 50%)",
  Entertainment: "hsl(185, 100%, 50%)",
  Health:        "hsl(3, 100%, 60%)",
  Shopping:      "hsl(290, 100%, 65%)",
  Utilities:     "hsl(25, 100%, 55%)",
  Housing:       "hsl(150, 100%, 50%)",
  Income:        "hsl(150, 100%, 50%)",
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
