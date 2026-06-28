import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { MessageCircle, Sparkles, Lock } from "lucide-react";
import styles from "./AssistantInterface.module.css";
import { ClerkConversation } from "@/components/custom/Clerk/ClerkConversation";

/**
 * The floating Clerk: the launcher button (bottom-right) and the right-hand
 * Sheet it opens. The conversation itself now lives in {@link ClerkConversation}
 * so the Command Deck can render the identical surface (P0 extraction). This
 * shell owns only the launcher and the drawer chrome (title + the can/can't line).
 */
export function AssistantInterface() {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          className={`${styles.assistantButton} assistant-button`}
          size="icon"
        >
          <MessageCircle className="h-6 w-6" />
        </Button>
      </SheetTrigger>
      <SheetContent className={`${styles.sheetContent} !bg-background !text-foreground`}>
        <SheetHeader>
          <SheetTitle className={`${styles.sheetTitle} !text-foreground`}>
            <Sparkles className="h-4 w-4 text-gold" />
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
  );
}
