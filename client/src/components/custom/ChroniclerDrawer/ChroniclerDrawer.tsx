/**
 * The Chronicler drawer (v4 §7.4, task 6).
 *
 * A `/`-summoned command-palette over ANY page — the existing assistant with a
 * skin. Plain assistant + zero persona in off mode; the Chronicler voice in
 * ambient/full. A persistent AI label sits in the header in ALL modes. Output is
 * buffered and firewalled server-side before it reaches here (we never render
 * raw model text).
 *
 * Tier 4: shares the visual language of the Clerk Sheet and the Command Deck —
 * a feather mark + AI seal in the header, the same left-ruled assistant / washed
 * user message treatment, a quiet empty state, and a gold-ringed input.
 */
import { useEffect, useRef, useState } from "react";
import { Feather, CornerDownLeft } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useFlags } from "@/store/gameMode";
import api from "@/lib/api";

interface DrawerMessage {
  role: "user" | "chronicler";
  text: string;
  kind?: string; // crisis | refusal | redirect | message | error
}

const CANNED = ["balance", "next bill", "boss", "chapter"];

export function ChroniclerDrawer({ defaultOpen = false }: { defaultOpen?: boolean } = {}) {
  const { gameLayer } = useFlags();
  const [open, setOpen] = useState(defaultOpen);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<DrawerMessage[]>([]);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  // `/` opens the drawer from anywhere (unless typing in a field).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      const typing = t?.tagName === "INPUT" || t?.tagName === "TEXTAREA";
      if (e.key === "/" && !typing) {
        e.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Keep the transcript pinned to the latest line.
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [messages, pending]);

  async function send(text: string) {
    if (!text.trim() || pending) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setQuery("");
    setPending(true);
    try {
      const res = await api.post("/game/chronicler/ask/", { message: text });
      setMessages((m) => [
        ...m,
        { role: "chronicler", text: res.data.text, kind: res.data.kind },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "chronicler", text: "The chronicle is unavailable right now.", kind: "error" },
      ]);
    } finally {
      setPending(false);
    }
  }

  const title = gameLayer ? "The Chronicler" : "Assistant";

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent
        side="right"
        className="flex w-full max-w-md flex-col p-0 !bg-background !text-foreground"
        data-testid="chronicler-drawer"
      >
        {/* Header — the persistent AI label is ALWAYS present, every mode. */}
        <div className="flex items-center justify-between border-b border-rule-strong/40 px-4 py-3">
          <span className="flex items-center gap-2">
            <Feather className="h-4 w-4 text-gold" aria-hidden />
            <span className="font-display text-sm font-semibold text-foreground">{title}</span>
          </span>
          <span
            data-testid="ai-label"
            className="rounded border border-rule-strong/40 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground"
          >
            AI
          </span>
        </div>

        {/* Transcript */}
        <div
          ref={transcriptRef}
          className="flex-1 space-y-3 overflow-y-auto px-4 py-4"
          data-testid="drawer-transcript"
        >
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <Feather className="h-6 w-6 text-muted-foreground/50" aria-hidden />
              <p className="font-sans text-sm text-muted-foreground">
                {gameLayer ? "Ask the chronicle anything." : "Ask the assistant anything."}
              </p>
              <p className="max-w-[16rem] font-sans text-xs text-muted-foreground/70">
                Try a shortcut below, or type your own question.
              </p>
            </div>
          ) : (
            messages.map((m, i) =>
              m.role === "user" ? (
                <p
                  key={i}
                  data-testid="msg-user"
                  className="ml-auto w-fit max-w-[85%] bg-wash px-3 py-1.5 text-right font-sans text-sm text-foreground"
                >
                  {m.text}
                </p>
              ) : (
                <p
                  key={i}
                  data-testid="msg-chronicler"
                  className={`max-w-[92%] border-l-2 pl-3 font-sans text-sm ${
                    m.kind === "error" || m.kind === "crisis"
                      ? "border-l-debit/60 text-foreground"
                      : "border-l-gold/50 text-muted-foreground"
                  }`}
                >
                  {m.text}
                </p>
              )
            )
          )}
          {pending && (
            <p className="border-l-2 border-l-gold/30 pl-3 font-sans text-sm italic text-muted-foreground/70">
              The chronicle is being written…
            </p>
          )}
        </div>

        {/* Canned commands + input */}
        <div className="border-t border-rule-strong/40 p-3">
          <div className="mb-2 flex flex-wrap gap-1">
            {CANNED.map((c) => (
              <button
                key={c}
                data-testid={`canned-${c.replace(" ", "-")}`}
                onClick={() => send(c)}
                disabled={pending}
                className="press border border-rule-strong/40 bg-card px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground transition-colors hover:bg-wash hover:text-foreground disabled:opacity-50"
              >
                {c}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(query);
            }}
            className="flex items-center gap-2 border border-rule-strong/40 bg-card px-3 py-2 focus-within:border-gold/60"
          >
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask the chronicle…"
              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
              data-testid="drawer-input"
            />
            <button
              type="submit"
              aria-label="Send"
              disabled={!query.trim() || pending}
              className="press grid h-6 w-6 shrink-0 place-items-center text-muted-foreground transition-colors hover:text-gold disabled:opacity-40"
            >
              <CornerDownLeft className="h-4 w-4" />
            </button>
          </form>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default ChroniclerDrawer;
