/**
 * IntensitySelector — the Off / Ambient / Full game-mode dial.
 *
 * Instant and reversible: clicking a level switches the mode live (no reload, no
 * confirm dialog — dialing down is a feature, autonomy is the point, v4). It
 * reads and writes the mode through the GameModeProvider, and labels itself via
 * the term catalog. Reusable: Settings uses it now; the Keeper sheet (package
 * 04) will reuse the same component.
 */
import { useGameMode, type GameMode } from "@/store/gameMode";
import { useTerm } from "@/store/gameMode";
import { cn } from "@/lib/utils";

const LEVELS: readonly GameMode[] = ["off", "ambient", "full"];

export function IntensitySelector() {
  const { mode, setMode } = useGameMode();
  const title = useTerm("settings.intensity.title");
  const description = useTerm("settings.intensity.description");

  return (
    <div data-testid="intensity-selector">
      <p className="font-display text-base font-semibold">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {LEVELS.map((level) => (
          <IntensityOption
            key={level}
            level={level}
            active={mode === level}
            onSelect={() => setMode(level)}
          />
        ))}
      </div>
    </div>
  );
}

function IntensityOption({
  level,
  active,
  onSelect,
}: {
  level: GameMode;
  active: boolean;
  onSelect: () => void;
}) {
  const label = useTerm(`settings.intensity.${level}`);
  const desc = useTerm(`settings.intensity.${level}.desc`);
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onSelect}
      className={cn(
        "press flex flex-col items-start gap-1 border px-3 py-3 text-left transition-colors",
        active
          ? "border-gold bg-gold/10 text-foreground"
          : "border-rule-strong/40 bg-card text-muted-foreground hover:bg-wash hover:text-foreground"
      )}
    >
      <span className="font-sans text-[11px] font-semibold uppercase tracking-[0.16em]">
        {label}
      </span>
      <span className="text-xs leading-snug">{desc}</span>
    </button>
  );
}

export default IntensitySelector;
