/**
 * <Term k="nav.budgets" /> — the dual-labeling primitive (v4 §4).
 *
 * Renders the current-mode term for the key. In `full` mode the plain (off)
 * term is ALWAYS reachable via `title` + `aria-label` — the one-tap / hover
 * reveal that makes the game vocabulary radically transparent. In off and
 * ambient modes it renders a bare text node so the DOM is pixel-identical to
 * the pre-game app (off-mode contract).
 *
 * This is one of the few places allowed to consult the mode (via the provider
 * hooks), so components never branch on `mode` themselves.
 */
import { useGameMode } from "@/store/gameMode";

interface TermProps {
  /** The flat catalog key, e.g. "nav.budgets". */
  k: string;
}

export function Term({ k }: TermProps) {
  const { mode, term, plainTerm } = useGameMode();
  const label = term(k);

  // Off/ambient: bare text, no wrapper — preserves the existing DOM exactly.
  if (mode !== "full") {
    return <>{label}</>;
  }

  // Full: wrap so the plain term is always one hover/tap away.
  const plain = plainTerm(k);
  return (
    <span title={plain} aria-label={plain} data-term={k}>
      {label}
    </span>
  );
}

export default Term;
