/**
 * Client-side guidance for the Clerk's composer — slash commands and ghost-text
 * completion. Both are PURELY local (a static corpus, no LLM call): they make
 * typing feel guided without spending the per-user cost budget or adding latency.
 * Slash commands map to the assistant's real tools/actions.
 */

export interface SlashCommand {
  /** The token after the slash, e.g. "rule" for /rule. */
  cmd: string;
  label: string;
  hint: string;
  /** Pre-fill this prompt (the user reviews + sends). */
  prompt?: string;
  /** Or run a local action instead of pre-filling. */
  action?: "clear";
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: "rule", label: "Describe a rule", hint: "Set aside money or get notified on a condition", prompt: "Help me write a rule. I want to " },
  { cmd: "goal", label: "Add a goal", hint: "Start a new savings goal", prompt: "Help me set up a goal to " },
  { cmd: "whatif", label: "Plan a what-if", hint: "Model a change to your forecast", prompt: "What if " },
  { cmd: "spent", label: "Check spending", hint: "How much you've spent lately", prompt: "How much have I spent this week?" },
  { cmd: "subscriptions", label: "Review subscriptions", hint: "Find price creep or things to cancel", prompt: "Review my subscriptions for price creep or anything I could cancel." },
  { cmd: "categorize", label: "Sort transactions", hint: "Categorize recent entries", prompt: "Help me categorize my recent transactions." },
  { cmd: "tax", label: "Tax check", hint: "Possible deductions (if tax features are on)", prompt: "Which of my recent expenses might be tax-deductible?" },
  { cmd: "clear", label: "Clear the conversation", hint: "Start fresh", action: "clear" },
];

/** Whether the input is an in-progress slash token ("/", "/ru") — the menu is
 *  only open while the WHOLE input is a single slash word, so it closes the
 *  moment a command pre-fills a longer prompt. */
export function parseSlash(input: string): { open: boolean; query: string } {
  const m = /^\/(\w*)$/.exec(input);
  return m ? { open: true, query: m[1].toLowerCase() } : { open: false, query: "" };
}

export function filterSlash(query: string): SlashCommand[] {
  if (!query) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter(
    (c) => c.cmd.startsWith(query) || c.label.toLowerCase().includes(query)
  );
}

/** A small corpus of common prompts the ghost-completion can finish. */
export const GHOST_CORPUS: string[] = [
  "How much have I spent this week?",
  "How much have I spent this month?",
  "What's my biggest expense category?",
  "Am I on track with my budgets?",
  "Show me my recent transactions",
  "How does this month compare to last?",
  "What subscriptions am I paying for?",
  "What can I afford to spend this week?",
  "When will I reach my savings goal?",
  "Why was I charged this much?",
];

/**
 * Find a single completion whose start matches the typed text (case-insensitive),
 * for an above-input "Tab to complete" hint. Suppressed for slash input, very
 * short input, or when the text already equals a corpus entry. `extra` lets the
 * caller fold in the current section's starter.
 */
export function ghostCompletion(input: string, extra: string[] = []): string | null {
  const v = input.replace(/^\s+/, "");
  if (v.length < 3 || v.startsWith("/")) return null;
  const lower = v.toLowerCase();
  const pool = [...extra, ...GHOST_CORPUS];
  for (const p of pool) {
    const pl = p.toLowerCase();
    if (pl.startsWith(lower) && p.length > v.length) return p;
  }
  return null;
}
