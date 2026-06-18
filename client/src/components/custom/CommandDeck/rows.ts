import type { LucideIcon } from "lucide-react";
import { NAV_ITEMS, NAV_GROUPS, type NavGroup } from "@/components/layout/nav";

/**
 * The Command Deck's unified result model. The ⌘K surface mixes three kinds of
 * row on one keyboard-navigable list:
 *  - `destination` — a nav jump (the existing NAV_ITEMS, filtered identically).
 *  - `action`      — a quick deterministic action (add transaction, link bank…).
 *  - `agent`       — route free text to the Clerk (the assistant pipeline).
 */
export type DeckRowKind = "agent" | "action" | "destination";

export type DeckGroup = "ask" | "actions" | NavGroup;

interface DeckRowBase {
  id: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  group: DeckGroup;
}

export interface DestinationRow extends DeckRowBase {
  kind: "destination";
  to: string;
  folio: string;
}

export interface ActionRow extends DeckRowBase {
  kind: "action";
  run: () => void;
  disabled?: boolean;
}

export interface AgentRow extends DeckRowBase {
  kind: "agent";
  intent: string;
}

export type DeckRow = DestinationRow | ActionRow | AgentRow;

/** Group order + headings for the deck list (Ask → Actions → the nav groups). */
export const DECK_GROUPS: { key: DeckGroup; label: string }[] = [
  { key: "ask", label: "Ask the Clerk" },
  { key: "actions", label: "Actions" },
  ...NAV_GROUPS,
];

/**
 * Destinations, built from the SAME mode/tax filter NavPalette uses so the deck
 * never regresses nav gating: a game entry only appears with the game layer on,
 * the tax entry only with the server tax flag on.
 */
export function buildDestinations(gameLayer: boolean, taxEnabled: boolean): DestinationRow[] {
  return NAV_ITEMS.filter(
    (i) => (!i.gameOnly || gameLayer) && (!i.taxOnly || taxEnabled)
  ).map((i) => ({
    kind: "destination",
    id: `dest:${i.to}`,
    label: i.label,
    icon: i.icon,
    group: i.group,
    to: i.to,
    folio: i.folio,
  }));
}

/** Case-insensitive label/hint match used as the user types. */
export function matchesQuery(row: DeckRow, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return (
    row.label.toLowerCase().includes(needle) ||
    (row.hint?.toLowerCase().includes(needle) ?? false)
  );
}
