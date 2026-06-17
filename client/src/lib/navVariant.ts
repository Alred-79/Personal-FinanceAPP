import { useSyncExternalStore } from "react";

/**
 * TEMP — nav-style comparison switch. Three navigation treatments are wired up
 * at once so the look can be chosen live; the winner is kept and this module
 * (plus the losing variants + the header switcher) is deleted afterward.
 *
 *  - "tabs"    : today's top tab bar + a "Tools ▾" overflow popover
 *  - "sidebar" : a collapsible left rail (icon → expands on hover)
 *  - "cmdk"    : a slim top bar + a ⌘K "jump to" command palette
 *
 * Backed by localStorage and reactive across Header and AppShell via a custom
 * event, so flipping it updates both surfaces without a reload.
 */
export type NavVariant = "tabs" | "sidebar" | "cmdk";

const KEY = "persfin-nav-variant";
const EVENT = "persfin-nav-variant-change";
const DEFAULT: NavVariant = "tabs";

export const NAV_VARIANTS: { key: NavVariant; label: string }[] = [
  { key: "tabs", label: "Tabs" },
  { key: "sidebar", label: "Sidebar" },
  { key: "cmdk", label: "⌘K" },
];

export function getNavVariant(): NavVariant {
  if (typeof window === "undefined") return DEFAULT;
  const v = window.localStorage.getItem(KEY);
  return v === "sidebar" || v === "cmdk" || v === "tabs" ? v : DEFAULT;
}

export function setNavVariant(v: NavVariant): void {
  window.localStorage.setItem(KEY, v);
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export function useNavVariant(): NavVariant {
  return useSyncExternalStore(subscribe, getNavVariant, () => DEFAULT);
}
