import {
  House,
  Utensils,
  Bus,
  Droplet,
  Drama,
  Briefcase,
  Wrench,
  Store,
  ArrowLeftRight,
  Plane,
  Shapes,
  HeartPulse,
  Dumbbell,
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
  Service: Wrench,
  Shops: Store,
  Shopping: Store,
  Transfer: ArrowLeftRight,
  Travel: Plane,
  Health: HeartPulse,
  Fitness: Dumbbell,
  Other: Shapes,
};

export function categoryIcon(category: string): LucideIcon {
  return ICONS[category] ?? Shapes;
}
