import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useStore } from "@/store/store";
import { useFlags } from "@/store/gameMode";
import { NAV_ITEMS, NAV_GROUPS, type NavItem } from "@/components/layout/nav";

/**
 * Nav Variant C — a ⌘K "jump to" command palette. A slim top bar pairs with
 * this; ⌘/Ctrl-K (or the header button) opens it, you type to filter every
 * destination, ↑/↓ to move, ↵ to go. Distinct from the Chronicler's `/` key so
 * the two don't collide.
 */
export function NavPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const { gameLayer } = useFlags();
  const taxEnabled = useStore((s) => s.taxFeaturesEnabled);
  const freelancerEnabled = useStore((s) => s.freelancerModeEnabled);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const items = useMemo(
    () =>
      NAV_ITEMS.filter(
        (i) =>
          (!i.gameOnly || gameLayer) &&
          (!i.taxOnly || taxEnabled) &&
          (!i.freelancerOnly || freelancerEnabled)
      ),
    [gameLayer, taxEnabled, freelancerEnabled]
  );

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((i) => i.label.toLowerCase().includes(q));
  }, [items, query]);

  // Reset the cursor/query whenever the palette opens; clamp on result changes.
  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
    }
  }, [open]);
  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, results.length - 1)));
  }, [results.length]);

  const go = (item: NavItem | undefined) => {
    if (!item) return;
    onOpenChange(false);
    navigate(item.to);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(results[active]);
    }
  };

  // Keep the active row scrolled into view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  let idx = -1;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="top-[18%] max-w-lg translate-y-0 gap-0 p-0"
        onKeyDown={onKeyDown}
      >
        <DialogTitle className="sr-only">Jump to a page</DialogTitle>
        <div className="flex items-center gap-2.5 border-b border-rule-strong/40 px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Jump to…"
            className="w-full bg-transparent font-sans text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden shrink-0 border border-rule-strong/40 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:block">
             esc
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto py-2">
          {results.length === 0 ? (
            <p className="px-4 py-6 text-center font-sans text-sm italic text-muted-foreground">
              Nothing matches “{query}”.
            </p>
          ) : (
            NAV_GROUPS.map(({ key, label }) => {
              const groupItems = results.filter((i) => i.group === key);
              if (groupItems.length === 0) return null;
              return (
                <div key={key} className="mb-1">
                  <p className="px-4 py-1 font-sans text-[9px] uppercase tracking-[0.22em] text-muted-foreground/60">
                    {label}
                  </p>
                  {groupItems.map((item) => {
                    idx += 1;
                    const i = idx;
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.to}
                        data-idx={i}
                        onMouseMove={() => setActive(i)}
                        onClick={() => go(item)}
                        className={cn(
                          "flex w-full items-center gap-3 px-4 py-2 text-left font-sans text-[13px] transition-colors",
                          i === active
                            ? "bg-wash text-foreground"
                            : "text-muted-foreground"
                        )}
                      >
                        <Icon className="h-[15px] w-[15px] shrink-0 opacity-80" />
                        <span className="flex-1">{item.label}</span>
                        <span className="font-mono text-[9px] text-muted-foreground/50">
                          {item.folio}
                        </span>
                      </button>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
