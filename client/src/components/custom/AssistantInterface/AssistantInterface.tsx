import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Lock } from "lucide-react";
import { motion } from "motion/react";
import styles from "./AssistantInterface.module.css";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { ClerkConversation } from "@/components/custom/Clerk/ClerkConversation";
import { ClerkPresence } from "@/components/custom/Clerk/ClerkPresence";
import { ClerkPortrait } from "@/components/custom/Clerk/ClerkPortrait";
import {
  useClerkSuggestion,
  fetchClerkSuggestions,
  isSilenced,
  silenceNudges,
  hasNudged,
  markNudged,
  nudgeCount,
  MAX_SESSION_NUDGES,
  type ClerkSuggestion,
} from "@/hooks/useClerkSuggestions";

const NUDGE_DELAY_MS = 1400;
const NUDGE_VISIBLE_MS = 7000;

/**
 * The floating Clerk: the engraved-portrait launcher (bottom-right) and the
 * right-hand window it opens. The Sheet is controlled so the portrait button —
 * not a Radix trigger — owns opening, and the same portrait docks into the
 * header. This component also orchestrates the contextual layer: it maps the
 * current section to a suggestion, fires an at-most-once-per-section "tap-the-
 * glass" nudge, and pre-fills the input when a ticket is activated.
 */
export function AssistantInterface() {
  const location = useLocation();
  const suggestion = useClerkSuggestion(location.pathname);
  const [enriched, setEnriched] = useState<ClerkSuggestion | null>(null);
  const [open, setOpen] = useState(false);
  const [seed, setSeed] = useState("");
  const [autoNudge, setAutoNudge] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const reduce = useReducedMotion();

  // Data-aware enrichment (server flag default-OFF → 404 → stays null → static
  // floor is used). Fetches on section change; the static `suggestion` still
  // gates WHETHER to nudge, while `active` decides WHAT the ticket says.
  useEffect(() => {
    let alive = true;
    setEnriched(null);
    void fetchClerkSuggestions(location.pathname).then((list) => {
      if (alive && list && list.length) setEnriched(list[0]);
    });
    return () => {
      alive = false;
    };
  }, [location.pathname]);

  const active = enriched ?? suggestion;

  // Auto "tap-the-glass": at most once per section per session, after a short
  // settle delay, never when silenced or already open. Hover tickets are
  // separate (ClerkPresence) and always available.
  useEffect(() => {
    setAutoNudge(false);
    const path = location.pathname;
    if (open || !suggestion || suggestion.auto === false) return;
    if (isSilenced() || hasNudged(path) || nudgeCount() >= MAX_SESSION_NUDGES) return;

    const show = setTimeout(() => {
      setAutoNudge(true);
      markNudged(path);
    }, NUDGE_DELAY_MS);
    const hide = setTimeout(
      () => setAutoNudge(false),
      NUDGE_DELAY_MS + NUDGE_VISIBLE_MS
    );
    return () => {
      clearTimeout(show);
      clearTimeout(hide);
    };
  }, [location.pathname, open, suggestion]);

  const openBlank = () => {
    setSeed("");
    setOpen(true);
  };
  const activate = () => {
    setSeed(active?.prompt ?? "");
    setAutoNudge(false);
    setOpen(true);
  };
  const silence = () => {
    silenceNudges();
    setAutoNudge(false);
  };

  return (
    <>
      <ClerkPresence
        open={open}
        onOpen={openBlank}
        suggestionLabel={active?.label}
        autoNudge={autoNudge}
        onActivate={activate}
        onSilence={silence}
      />

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className={`${styles.sheetContent} !bg-background !text-foreground`}>
          <SheetHeader>
            <SheetTitle className={`${styles.sheetTitle} !text-foreground`}>
              <motion.span
                className="inline-block text-foreground"
                animate={speaking && !reduce ? { scale: [1, 1.07, 1] } : { scale: 1 }}
                transition={
                  speaking && !reduce
                    ? { duration: 0.5, repeat: Infinity, ease: "easeInOut" }
                    : { duration: 0.2 }
                }
              >
                <ClerkPortrait
                  size={38}
                  blink={false}
                  state={speaking ? "speaking" : "resting"}
                />
              </motion.span>
              <span className="font-display text-lg font-semibold">The Clerk</span>
            </SheetTitle>
            <p className="text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
              At your service
            </p>
            {/* persistent can/can't line — borrow the read-only credibility (§4) */}
            <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-snug text-muted-foreground">
              <Lock className="mt-px h-3 w-3 shrink-0 text-gold" aria-hidden />
              <span>
                I can see your transactions and draft actions. I can&rsquo;t move money
                or see full account numbers.
              </span>
            </p>
          </SheetHeader>

          <ClerkConversation seedPrompt={seed} onSpeakingChange={setSpeaking} />
        </SheetContent>
      </Sheet>
    </>
  );
}
