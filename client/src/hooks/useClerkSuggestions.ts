import { useMemo } from "react";
import { apiBase } from "@/lib/apiBase";

/**
 * A section-aware offer from the Clerk. `label` is the margin-note ticket the
 * user sees; `prompt` is what gets PRE-FILLED into the input on activation —
 * never auto-sent (that protects the per-user cost budget). `auto: false` means
 * "only ever on hover", never an unprompted nudge (used on the home screen the
 * user lands on every session).
 *
 * This is the instant, offline fallback layer. P6 adds a heuristic backend
 * endpoint that can ENRICH these with data-aware lines ("You're $40 over on
 * dining — want options?"); the map below is always the floor.
 */
export interface ClerkSuggestion {
  label: string;
  prompt: string;
  auto?: boolean;
}

const SECTION_SUGGESTIONS: Record<string, ClerkSuggestion> = {
  "/": { label: "Good day. Shall we look at anything?", prompt: "", auto: false },
  "/accounts": {
    label: "Want a quick read on your balances?",
    prompt: "Give me a quick read on my account balances.",
  },
  "/transactions": {
    label: "Need a hand sorting these entries?",
    prompt: "Help me categorize my recent transactions.",
  },
  "/budgets": {
    label: "Shall I see where this week's spending stands?",
    prompt: "How am I tracking against my budgets this week?",
  },
  "/goals": {
    label: "Want a faster way to reach a goal?",
    prompt: "Suggest a way I could reach one of my goals faster.",
  },
  "/forecast": {
    label: "Curious what a what-if would do to this line?",
    prompt: "What if ",
  },
  "/subscriptions": {
    label: "Shall I hunt for creeping charges?",
    prompt: "Review my subscriptions for price creep or anything I could cancel.",
  },
  "/rules": {
    label: "Want to describe a rule in plain words?",
    prompt: "Help me write a rule. I want to ",
  },
  "/reconcile": {
    label: "Want help untangling these imports?",
    prompt: "Help me reconcile my imported transactions.",
  },
  "/tax": {
    label: "Tag anything here for Schedule C?",
    prompt: "Which of my recent expenses might be tax-deductible?",
  },
};

/** Resolve the suggestion for a path: exact match, then longest route prefix. */
export function suggestionForPath(pathname: string): ClerkSuggestion | null {
  if (SECTION_SUGGESTIONS[pathname]) return SECTION_SUGGESTIONS[pathname];
  const key = Object.keys(SECTION_SUGGESTIONS)
    .filter((k) => k !== "/" && pathname.startsWith(k))
    .sort((a, b) => b.length - a.length)[0];
  return key ? SECTION_SUGGESTIONS[key] : null;
}

export function useClerkSuggestion(pathname: string): ClerkSuggestion | null {
  return useMemo(() => suggestionForPath(pathname), [pathname]);
}

/* ── Data-aware enrichment (P6, server flag default-OFF) ────────────────────
   The backend GET /assistant/suggestions/ returns heuristic, data-aware
   starters for the section ("You're $40 from 'New roof' — want a plan?"). It's
   purely an ENRICHMENT over the static map above. When the flag is off the
   endpoint 404s; we remember that and stop asking for the rest of the session. */

let suggestionsDisabled = false;

export async function fetchClerkSuggestions(
  context: string
): Promise<ClerkSuggestion[] | null> {
  if (suggestionsDisabled) return null;
  try {
    const res = await fetch(
      `${apiBase}/assistant/suggestions/?context=${encodeURIComponent(context)}`,
      { credentials: "include" }
    );
    if (res.status === 404) {
      suggestionsDisabled = true; // flag off — never retry this session
      return null;
    }
    if (!res.ok) return null;
    const data: unknown = await res.json();
    if (!Array.isArray(data)) return null;
    return data.filter(
      (s): s is ClerkSuggestion =>
        !!s && typeof s.label === "string" && typeof s.prompt === "string"
    );
  } catch {
    return null;
  }
}

/* ── Frequency model (session-scoped) ──────────────────────────────────────
   Restrained concierge: the auto "tap-the-glass" nudge fires at most ONCE per
   section per session, and a single dismiss silences all auto-nudges for the
   rest of the session. Hover tickets are user-initiated and never gated. */

/** Hard ceiling on unprompted nudges per session, across all sections, so a
 * browsing session can never rack them up. Hover tickets remain unlimited. */
export const MAX_SESSION_NUDGES = 3;

const SILENCED_KEY = "clerk:nudges-silenced";
const NUDGED_KEY = "clerk:nudged-routes";

export function isSilenced(): boolean {
  try {
    return sessionStorage.getItem(SILENCED_KEY) === "1";
  } catch {
    return false;
  }
}

export function silenceNudges(): void {
  try {
    sessionStorage.setItem(SILENCED_KEY, "1");
  } catch {
    /* sessionStorage unavailable — degrade to no-persistence */
  }
}

function nudgedRoutes(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(NUDGED_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

export function hasNudged(route: string): boolean {
  return nudgedRoutes().has(route);
}

/** Distinct sections auto-nudged this session (each fires at most once). */
export function nudgeCount(): number {
  return nudgedRoutes().size;
}

export function markNudged(route: string): void {
  try {
    const set = nudgedRoutes();
    set.add(route);
    sessionStorage.setItem(NUDGED_KEY, JSON.stringify([...set]));
  } catch {
    /* ignore */
  }
}
