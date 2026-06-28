import { useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Lock } from "lucide-react";
import styles from "./AssistantInterface.module.css";
import { ClerkConversation } from "@/components/custom/Clerk/ClerkConversation";
import { ClerkPresence } from "@/components/custom/Clerk/ClerkPresence";
import { ClerkPortrait } from "@/components/custom/Clerk/ClerkPortrait";

/**
 * The floating Clerk: the engraved-portrait launcher (bottom-right) and the
 * right-hand window it opens. The launcher is {@link ClerkPresence}; the
 * conversation is {@link ClerkConversation} (shared with the Command Deck). The
 * Sheet is controlled so the rich portrait button — not a Radix trigger — owns
 * opening, and the same portrait docks into the window header.
 */
export function AssistantInterface() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <ClerkPresence open={open} onOpen={() => setOpen(true)} />

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className={`${styles.sheetContent} !bg-background !text-foreground`}>
          <SheetHeader>
            <SheetTitle className={`${styles.sheetTitle} !text-foreground`}>
              <span className="text-foreground">
                <ClerkPortrait size={38} blink={false} />
              </span>
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

          <ClerkConversation />
        </SheetContent>
      </Sheet>
    </>
  );
}
