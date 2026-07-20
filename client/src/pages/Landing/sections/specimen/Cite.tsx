import { cn } from "@/lib/utils";
import type { Citation } from "./specimenData";

/**
 * A citation: file path + symbol/test NAME, never a line number — a line number
 * is stale on the next edit, and a stale citation is worse than none. Every
 * name rendered here was read out of the file it names before it shipped, and
 * specimen-sheet.test.tsx re-checks the shape on every run.
 *
 * `compact` is the register treatment: the kind chip drops away because the
 * path already says `tests/`, and the type steps down so a level's citations
 * never compete with the four callouts' proof block.
 */
export function Cite({ path, symbol, kind, compact = false }: Citation & { compact?: boolean }) {
  return (
    <span className={cn("spx-cite", compact && "spx-cite--compact")}>
      <span className={cn("spx-cite__kind", `spx-cite__kind--${kind}`)}>{kind}</span>
      <code className="spx-cite__path">{path}</code>
      {symbol && (
        <>
          <span className="spx-cite__sep" aria-hidden>
            ·
          </span>
          <code className="spx-cite__sym">{symbol}</code>
        </>
      )}
    </span>
  );
}
