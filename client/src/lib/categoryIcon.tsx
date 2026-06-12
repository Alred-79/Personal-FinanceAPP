import {
  House,
  Utensils,
  Bus,
  Droplet,
  Drama,
  Briefcase,
  Hammer,
  Store,
  ArrowLeftRight,
  Plane,
  Shapes,
  HeartPulse,
  type LucideIcon,
} from "lucide-react";

/** Maps a transaction category to its engraved glyph. */
const ICONS: Record<string, LucideIcon> = {
  Housing: House,
  Food: Utensils,
  "Food and Drink": Utensils,
  Transportation: Bus,
  Transport: Bus,
  Utilities: Droplet,
  Entertainment: Drama,
  Recreation: Drama,
  Work: Briefcase,
  Income: Briefcase,
  Service: Hammer,
  Shops: Store,
  Shopping: Store,
  Transfer: ArrowLeftRight,
  Travel: Plane,
  Health: HeartPulse,
  Other: Shapes,
};

export function categoryIcon(category: string): LucideIcon {
  return ICONS[category] ?? Shapes;
}
