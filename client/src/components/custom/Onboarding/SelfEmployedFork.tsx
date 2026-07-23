import { useStore } from "@/store/store";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Seal } from "@/components/engraving/Seal";

/** Optional personalization shown after the core Overview answer is usable. */
export function SelfEmployedFork() {
  const isLoggedIn = useStore((s) => s.isLoggedIn);
  const settingsLoaded = useStore((s) => s.settingsLoaded);
  const selfEmployed = useStore((s) => s.selfEmployed);
  const dismissed = useStore((s) => s.selfEmployedPromptDismissed);
  const setSelfEmployed = useStore((s) => s.setSelfEmployed);
  const dismiss = useStore((s) => s.dismissSelfEmployedPrompt);

  if (!isLoggedIn || !settingsLoaded || selfEmployed !== null || dismissed) {
    return null;
  }

  return (
    <Card className="mt-6" aria-labelledby="work-money-personalization">
      <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <div className="hidden shrink-0 sm:block" aria-hidden>
          <Seal size={48} label="Optional personalization" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 id="work-money-personalization" className="font-sans text-base font-semibold">
            Personalize for freelance or 1099 income?
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Put uneven-income and tax tools closer at hand. This changes page emphasis
            only; it never moves money and you can change it in Settings.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 sm:justify-end">
          <Button type="button" onClick={() => setSelfEmployed(true)}>
            Yes, personalize
          </Button>
          <Button type="button" variant="outline" onClick={() => setSelfEmployed(false)}>
            Regular paycheck
          </Button>
          <Button type="button" variant="ghost" onClick={dismiss}>
            Not now
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
