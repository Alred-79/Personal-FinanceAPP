import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "motion/react";
import {
  Command,
  Sparkles,
  CornerDownLeft,
  ArrowLeft,
  Plus,
  Building2,
  LineChart,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useStore } from "@/store/store";
import { useFlags } from "@/store/gameMode";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { useAssistantChat } from "@/hooks/useAssistantChat";
import { ProposalCard } from "@/components/custom/AssistantInterface/ProposalCard";
import BridgeCard from "@/components/custom/BridgeCard/BridgeCard";
import {
  buildDestinations,
  matchesQuery,
  DECK_GROUPS,
  type DeckRow,
  type ActionRow,
  type AgentRow,
} from "./rows";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * The Command Deck — ⌘K as a deck that *acts*, not just navigates. The page
 * recedes behind a veil, a centred deck inks in, and one keyboard-driven list
 * mixes destinations (the nav), quick actions (add transaction, link bank, plan
 * a what-if), and a free-text "ask the Clerk" row. Asking switches the deck into
 * a compact reply view that REUSES the assistant pipeline (`useAssistantChat`)
 * and the shared propose→confirm cards, so money-moving intents still flow
 * through ConfirmCard — never straight off a palette row.
 *
 * It supersedes NavPalette behind the always-on `commandDeck` flag and takes the
 * same `{ open, onOpenChange }` props, plus the bank-link handler lifted from
 * the Header (the same one the Sidebar uses).
 */
export function CommandDeck({
  open,
  onOpenChange,
  onConnectBank,
  canConnectBank,
  bankAvailable,
  assistantAvailable,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConnectBank: () => void;
  canConnectBank: boolean;
  bankAvailable: boolean;
  assistantAvailable: boolean;
}) {
  const navigate = useNavigate();
  const { gameLayer } = useFlags();
  const taxEnabled = useStore((s) => s.taxFeaturesEnabled);
  const freelancerEnabled = useStore((s) => s.freelancerModeEnabled);
  const requestAddTransaction = useStore((s) => s.requestAddTransaction);
  const reduced = useReducedMotion();
  const chat = useAssistantChat();

  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [mode, setMode] = useState<"command" | "ask">("command");

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const deckRef = useRef<HTMLDivElement>(null);
  const replyRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  const close = () => onOpenChange(false);

  const destinations = useMemo(
    () => buildDestinations(gameLayer, taxEnabled, freelancerEnabled),
    [gameLayer, taxEnabled, freelancerEnabled]
  );

  // Quick actions close over the live handlers; money never moves from here —
  // add-txn opens the form, link-bank opens Plaid, what-if just navigates.
  const actions: ActionRow[] = useMemo(
    () => [
      {
        kind: "action",
        id: "act:add-txn",
        label: "Add a transaction",
        hint: "record a new entry",
        icon: Plus,
        group: "actions",
        run: () => {
          close();
          navigate("/transactions");
          requestAddTransaction();
        },
      },
      ...(bankAvailable ? [{
        kind: "action",
        id: "act:link-bank",
        label: "Link a bank",
        hint: "connect an account",
        icon: Building2,
        group: "actions",
        disabled: !canConnectBank,
        run: () => {
          close();
          onConnectBank();
        },
      } as ActionRow] : []),
      {
        kind: "action",
        id: "act:whatif",
        label: "Test a decision",
        hint: "open Decisions",
        icon: LineChart,
        group: "actions",
        run: () => {
          close();
          navigate("/forecast");
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bankAvailable, canConnectBank, navigate, requestAddTransaction]
  );

  // Group order: Ask (only with free text) → Actions → the nav groups. Each
  // filtered by the query; destinations keep their NAV_GROUPS section.
  const groups = useMemo(() => {
    const q = query.trim();
    const agentRow: AgentRow = {
      kind: "agent",
      id: "ask",
      label: `Ask the Clerk: “${q}”`,
      icon: Sparkles,
      group: "ask",
      intent: q,
    };
    return DECK_GROUPS.map((g) => {
      let rows: DeckRow[] = [];
      if (g.key === "ask") rows = q && assistantAvailable ? [agentRow] : [];
      else if (g.key === "actions") rows = actions.filter((a) => matchesQuery(a, q));
      else rows = destinations.filter((d) => d.group === g.key && matchesQuery(d, q));
      return { ...g, rows };
    }).filter((g) => g.rows.length > 0);
  }, [query, actions, assistantAvailable, destinations]);

  const flat = useMemo(() => groups.flatMap((g) => g.rows), [groups]);
  const activeId = flat[active]?.id;

  // Reset on open; capture focus to restore on close.
  useEffect(() => {
    if (open) {
      restoreRef.current = document.activeElement as HTMLElement | null;
      setQuery("");
      setActive(0);
      setMode("command");
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      restoreRef.current?.focus?.();
    }
  }, [open]);

  // Clamp the cursor as results shrink/grow.
  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, flat.length - 1)));
  }, [flat.length]);

  // Keep the active row in view.
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  // Pin the reply to the latest turn.
  useEffect(() => {
    if (mode === "ask" && replyRef.current) {
      replyRef.current.scrollTop = replyRef.current.scrollHeight;
    }
  }, [chat.messages, chat.isLoading, chat.proposal, chat.bridge, mode]);

  const enterAsk = (intent: string) => {
    if (!intent.trim()) return;
    setMode("ask");
    setQuery("");
    void chat.send(intent);
  };

  const backToCommand = () => {
    setMode("command");
    setQuery("");
    setActive(0);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const activate = (row: DeckRow | undefined) => {
    if (!row) return;
    if (row.kind === "destination") {
      close();
      navigate(row.to);
    } else if (row.kind === "action") {
      if (!row.disabled) row.run();
    } else {
      enterAsk(row.intent);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "Tab") {
      // Lightweight focus trap so Tab cycles inside the deck.
      const focusables = deckRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])'
      );
      if (focusables && focusables.length > 0) {
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
      return;
    }
    if (mode === "ask") {
      if (e.key === "Enter") {
        e.preventDefault();
        const q = query.trim();
        if (q) {
          setQuery("");
          void chat.send(q);
        }
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      activate(flat[active]);
    }
  };

  const veilAnim = {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: reduced ? 0 : 0.14, ease: EASE },
  };
  // x:-50% lives in the motion transform (not a Tailwind class) because motion
  // writes `transform` wholesale and would otherwise clobber -translate-x-1/2,
  // throwing the deck off-centre.
  const cardAnim = {
    initial: reduced
      ? { opacity: 0, x: "-50%" }
      : { opacity: 0, x: "-50%", y: -8, scale: 0.985 },
    animate: { opacity: 1, x: "-50%", y: 0, scale: 1 },
    exit: reduced
      ? { opacity: 0, x: "-50%" }
      : { opacity: 0, x: "-50%", y: -6, scale: 0.99 },
    transition: { duration: reduced ? 0 : 0.16, ease: EASE },
  };

  let idx = -1;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            {...veilAnim}
            onClick={close}
            aria-hidden
            className="fixed inset-0 z-40 bg-[hsl(222_32%_9%/0.55)] backdrop-blur-[2px]"
          />
          <motion.div
            {...cardAnim}
            ref={deckRef}
            role="dialog"
            aria-modal="true"
            aria-label="Command deck"
            onKeyDown={onKeyDown}
            className="plate fixed left-1/2 top-[14vh] z-50 w-[92vw] max-w-[620px] overflow-hidden bg-card shadow-2xl"
          >
            {/* header — nib + input + esc hint */}
            <div className="flex items-center gap-2.5 border-b border-rule-strong/40 px-4 py-3">
              {mode === "ask" ? (
                <button
                  type="button"
                  onClick={backToCommand}
                  aria-label="Back to commands"
                  className="press grid h-11 w-11 shrink-0 place-items-center text-gold hover:text-foreground"
                >
                  <ArrowLeft className="h-4 w-4" />
                </button>
              ) : (
                <Command className="h-4 w-4 shrink-0 text-gold" aria-hidden />
              )}
              <input
                ref={inputRef}
                role="combobox"
                aria-expanded={mode === "command"}
                aria-controls="command-deck-list"
                aria-activedescendant={mode === "command" ? activeId : undefined}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                placeholder={
                  mode === "ask"
                    ? "Ask a follow-up…"
                    : assistantAvailable
                    ? "Type a command, or ask the Clerk anything…"
                    : "Type a command or page name…"
                }
                className="w-full bg-transparent font-sans text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
              <kbd className="hidden shrink-0 border border-rule-strong/40 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:block">
                esc
              </kbd>
            </div>

            {mode === "command" ? (
              <div
                ref={listRef}
                id="command-deck-list"
                role="listbox"
                aria-label="Commands and destinations"
                className="max-h-[52vh] overflow-y-auto py-2"
              >
                {flat.length === 0 ? (
                  <p className="px-4 py-6 text-center font-sans text-sm italic text-muted-foreground">
                    Nothing matches “{query}”.
                  </p>
                ) : (
                  groups.map((g) => (
                    <div key={g.key} className="mb-1">
                      <p className="px-4 py-1 font-sans text-[9px] uppercase tracking-[0.22em] text-muted-foreground/60">
                        {g.label}
                      </p>
                      {g.rows.map((row) => {
                        idx += 1;
                        const i = idx;
                        const Icon = row.icon;
                        const isAction = row.kind === "action";
                        const disabled = isAction && (row as ActionRow).disabled;
                        return (
                          <button
                            key={row.id}
                            id={row.id}
                            role="option"
                            aria-selected={i === active}
                            data-idx={i}
                            disabled={disabled}
                            onMouseMove={() => setActive(i)}
                            onClick={() => activate(row)}
                            className={cn(
                              "flex w-full items-center gap-3 px-4 py-2 text-left font-sans text-[13px] transition-colors disabled:opacity-40",
                              i === active ? "bg-wash text-foreground" : "text-muted-foreground"
                            )}
                          >
                            <Icon
                              className={cn(
                                "h-[15px] w-[15px] shrink-0",
                                row.kind === "agent" || isAction
                                  ? "text-gold opacity-90"
                                  : "opacity-80"
                              )}
                            />
                            <span className="flex-1 truncate">{row.label}</span>
                            {row.kind === "destination" ? (
                              <span className="font-mono text-[9px] text-muted-foreground/50">
                                {row.folio}
                              </span>
                            ) : row.hint ? (
                              <span className="hidden font-sans text-[10px] text-muted-foreground/50 sm:inline">
                                {row.hint}
                              </span>
                            ) : null}
                            {i === active && (
                              <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  ))
                )}
              </div>
            ) : (
              <div ref={replyRef} className="max-h-[56vh] space-y-3 overflow-y-auto p-4">
                {chat.messages.map((m, i) => (
                  <div
                    key={i}
                    className={cn(
                      "flex",
                      m.role === "assistant" ? "justify-start" : "justify-end"
                    )}
                  >
                    <div
                      className={cn(
                        "max-w-[88%] px-3 py-2 font-sans text-sm",
                        m.role === "assistant"
                          ? "border-l-2 border-gold/50 text-foreground"
                          : "bg-wash text-foreground"
                      )}
                    >
                      {m.content}
                    </div>
                  </div>
                ))}
                {chat.proposal && (
                  <ProposalCard
                    proposal={chat.proposal}
                    onDismiss={chat.dismissProposal}
                    onView={(id) => {
                      close();
                      navigate(`/forecast?scenario=${id}`);
                    }}
                  />
                )}
                {chat.bridge && (
                  <BridgeCard bridge={chat.bridge} onDismiss={chat.dismissBridge} />
                )}
                {chat.actionMessages.length > 0 && (
                  <div className="space-y-1">
                    {chat.actionMessages.map((a) => (
                      <p
                        key={a.id}
                        className="font-sans text-[11px] italic text-muted-foreground"
                      >
                        {a.text}
                      </p>
                    ))}
                  </div>
                )}
                {chat.isLoading && (
                  <p className="font-sans text-sm italic text-muted-foreground">
                    The Clerk is considering…
                  </p>
                )}
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}

export default CommandDeck;
