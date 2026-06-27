import { useStore } from "@/store/store";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Seal } from "@/components/engraving/Seal";
import { ReadOnlyBadge } from "@/components/custom/Trust/ReadOnlyBadge";

/**
 * The first-run self-employed fork. The single most important branch for adoption:
 * a freelancer drowning in quarterly taxes is the user who'd actually pay. We ask
 * once and persist the answer client-side to foreground the freelancer surfaces.
 *
 * HONESTY (frontend re-eval): this is a UI-emphasis preference, NOT a setup that
 * moves money. The deeper freelancer tax desk ships OFF per workspace; when it's off
 * we say so plainly rather than promise something the default config can't deliver.
 *
 * Shows only when the user is logged in, settings have loaded, and the question
 * hasn't been answered yet (selfEmployed === null). Frontend-only; no backend.
 */
export function SelfEmployedFork() {
  const isLoggedIn = useStore((s) => s.isLoggedIn);
  const settingsLoaded = useStore((s) => s.settingsLoaded);
  const selfEmployed = useStore((s) => s.selfEmployed);
  const setSelfEmployed = useStore((s) => s.setSelfEmployed);
  const freelancerModeEnabled = useStore((s) => s.freelancerModeEnabled);

  const open = isLoggedIn && settingsLoaded && selfEmployed === null;

  return (
    <Dialog open={open}>
      {/* No close affordance — this is a one-time, two-button fork, not a dismiss. */}
      <DialogContent
        className="max-w-md rounded-none"
        onPointerDownOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
        hideClose
      >
        <DialogHeader className="items-center text-center">
          <div className="mb-3 flex justify-center">
            <Seal size={56} label="Personal Accounts · Personal Accounts" />
          </div>
          <p className="dept-label">First, one question</p>
          <DialogTitle className="font-display text-2xl font-semibold leading-tight">
            Do you work for yourself?
          </DialogTitle>
          <DialogDescription className="text-[0.92rem] leading-relaxed text-muted-foreground">
            1099, freelance, contractor, or a side gig that pays you directly — if
            that&rsquo;s you, we&rsquo;ll keep your tax and cash-flow tools up front:
            estimate what you&rsquo;ll owe, recommend how much to hold back, and hand
            you the set-aside to make in your own bank. We do the math; you make the move.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-2 grid gap-2.5">
          <Button
            size="lg"
            className="press w-full justify-center"
            onClick={() => setSelfEmployed(true)}
          >
            Yes — I&rsquo;m self-employed
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="press w-full justify-center"
            onClick={() => setSelfEmployed(false)}
          >
            No — I&rsquo;m on a regular paycheck
          </Button>
        </div>

        {!freelancerModeEnabled && (
          <p className="rounded-none border border-rule-strong/30 bg-card/60 px-3 py-2 text-center text-[11px] leading-relaxed text-muted-foreground">
            Heads up: the full tax desk switches on per workspace. Either way you can
            start a tax-reserve goal today, and the Clerk will estimate what you owe
            and hand you the set-aside.
          </p>
        )}

        <div className="mt-1 flex justify-center">
          <ReadOnlyBadge />
        </div>
        <p className="text-center text-[11px] text-muted-foreground">
          You can change this any time in Settings.
        </p>
      </DialogContent>
    </Dialog>
  );
}
