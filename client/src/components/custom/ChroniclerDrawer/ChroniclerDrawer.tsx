/**
 * The Chronicler drawer (v4 §7.4, task 6).
 *
 * A `/`-summoned command-palette over ANY page — the existing assistant with a
 * skin. Plain assistant + zero persona in off mode; the Chronicler voice in
 * ambient/full. A persistent AI label sits in the header in ALL modes. Output is
 * buffered and firewalled server-side before it reaches here (we never render
 * raw model text).
 */
import { useEffect, useRef, useState } from "react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useFlags } from "@/store/gameMode";
import api from "@/lib/api";

interface DrawerMessage {
  role: "user" | "chronicler";
  text: string;
  kind?: string; // crisis | refusal | redirect | message
}

const CANNED = ["balance", "next bill", "boss", "chapter"];

export function ChroniclerDrawer({ defaultOpen = false }: { defaultOpen?: boolean } = {}) {
  const { gameLayer } = useFlags();
  const [open, setOpen] = useState(defaultOpen);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<DrawerMessage[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

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

  async function send(text: string) {
    if (!text.trim()) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setQuery("");
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
    }
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="w-full max-w-md p-0" data-testid="chronicler-drawer">
        <div className="flex h-full flex-col">
          {/* Header — the persistent AI label is ALWAYS present, every mode. */}
          <div className="flex items-center justify-between border-b border-rule-strong/40 px-4 py-3">
            <span className="font-display text-sm font-semibold">
              {gameLayer ? "The Chronicler" : "Assistant"}
            </span>
            <span
              data-testid="ai-label"
              className="rounded border border-rule-strong/40 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground"
            >
              AI
            </span>
          </div>

          {/* Transcript */}
          <div className="flex-1 space-y-2 overflow-y-auto p-4" data-testid="drawer-transcript">
            {messages.map((m, i) => (
              <p
                key={i}
                data-testid={`msg-${m.role}`}
                className={m.role === "user" ? "text-right text-sm" : "text-sm text-muted-foreground"}
              >
                {m.text}
              </p>
            ))}
          </div>

          {/* Canned commands + input */}
          <div className="border-t border-rule-strong/40 p-3">
            <div className="mb-2 flex flex-wrap gap-1">
              {CANNED.map((c) => (
                <button
                  key={c}
                  data-testid={`canned-${c.replace(" ", "-")}`}
                  onClick={() => send(c)}
                  className="press border border-rule-strong/40 bg-card px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground hover:bg-wash"
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
            >
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask the chronicle…"
                className="w-full border border-rule-strong/40 bg-card px-3 py-2 text-sm outline-none"
                data-testid="drawer-input"
              />
            </form>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default ChroniclerDrawer;
