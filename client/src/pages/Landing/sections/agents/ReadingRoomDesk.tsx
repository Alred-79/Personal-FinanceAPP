import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import {
  DEFAULT_GRANTED,
  GATE_INDEX,
  REQUESTS,
  SCOPES,
  STATIONS,
  WRITE_TRUTH,
  type Request,
  type ScopeId,
} from "./readingRoomData";
import { AnswerDocket } from "./AnswerDocket";
import { EngineerSwitch } from "./EngineerSwitch";

/** How long a request dwells at each aperture before the next one opens. */
const DWELL_MS = 340;

type Outcome = {
  request: Request;
  /** Needed scopes the visitor hasn't granted. Empty = the request clears. */
  missing: ScopeId[];
  denied: boolean;
  /** The last station the request can reach. */
  finalIndex: number;
};

/**
 * The apparatus: a counter where you file a request, a rack of clauses that says
 * what it may read, the passage it travels, and the docket it comes back as.
 *
 * Nothing here loops on its own. A request moves only because you sent it, and
 * every scope change re-files it so the consequence is visible immediately.
 */
export function ReadingRoomDesk({
  engineer,
  onEngineerChange,
}: {
  engineer: boolean;
  onEngineerChange: (on: boolean) => void;
}) {
  const reduce = useReducedMotion();
  const [granted, setGranted] = useState<Set<ScopeId>>(() => new Set(DEFAULT_GRANTED));
  const [activeId, setActiveId] = useState<string | null>(null);
  /** Highest station index the current request has reached; -1 = nothing filed. */
  const [reached, setReached] = useState(-1);
  const runRef = useRef(0);

  const outcome: Outcome | null = useMemo(() => {
    const request = REQUESTS.find((r) => r.id === activeId);
    if (!request) return null;
    const missing = request.needs.filter((n) => !granted.has(n));
    const denied = missing.length > 0;
    return {
      request,
      missing,
      denied,
      finalIndex: denied ? GATE_INDEX : STATIONS.length - 1,
    };
  }, [activeId, granted]);

  /* The passage. Each send starts a fresh run; a run in flight is abandoned when
     a new one starts (the token check), so rapid clicking can't interleave two
     requests. Reduced motion skips the travel and shows the settled result. */
  useEffect(() => {
    runRef.current += 1;
    const token = runRef.current;

    if (!outcome) {
      setReached(-1);
      return;
    }
    if (reduce) {
      setReached(outcome.finalIndex);
      return;
    }

    setReached(-1);
    const timers: number[] = [];
    for (let i = 0; i <= outcome.finalIndex; i += 1) {
      timers.push(
        window.setTimeout(() => {
          if (runRef.current === token) setReached(i);
        }, DWELL_MS * (i + 1))
      );
    }
    return () => timers.forEach(clearTimeout);
  }, [outcome, reduce]);

  const travelling = outcome !== null && reached < outcome.finalIndex;
  const settled = outcome !== null && reached >= outcome.finalIndex;

  const toggleScope = useCallback((id: ScopeId) => {
    setGranted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const grantMissing = useCallback((ids: ScopeId[]) => {
    setGranted((prev) => new Set([...prev, ...ids]));
  }, []);

  return (
    <div className={cn("rr-room mt-10", engineer && "rr-room--engineer")}>
      <div className="rr-room__head">
        <div>
          <p className="rr-room__plate">The Reading Room</p>
          <p className="rr-room__note">
            An example ledger. A demonstration you can drive — not a live API call.
          </p>
        </div>
        <EngineerSwitch on={engineer} onChange={onEngineerChange} />
      </div>

      {/* ── the counter: pick a request ───────────────────────────────────── */}
      <div className="rr-slips" role="radiogroup" aria-label="Ask the room a question">
        {REQUESTS.map((r) => (
          <button
            key={r.id}
            type="button"
            role="radio"
            aria-checked={activeId === r.id}
            onClick={() => setActiveId(r.id)}
            className={cn("rr-slip", activeId === r.id && "is-filed")}
          >
            <span className="rr-slip__perf" aria-hidden />
            <span className="rr-slip__head">{r.filed}</span>
            <span className="rr-slip__q">{r.question}</span>
            <span className="rr-slip__file" aria-hidden>
              {activeId === r.id ? "Filed" : "File this"}
            </span>
          </button>
        ))}
      </div>

      <div className="rr-body">
        <ScopeRack
          granted={granted}
          onToggle={toggleScope}
          needs={outcome?.request.needs}
          missing={outcome?.missing}
        />

        <div className="rr-right">
          <Passage
            outcome={outcome}
            reached={reached}
            travelling={travelling}
            engineer={engineer}
          />

          <AnswerDocket
            outcome={outcome}
            settled={settled}
            engineer={engineer}
            onGrant={grantMissing}
          />
        </div>
      </div>

      {engineer && <WriteTruth />}
    </div>
  );
}

/* ── The rack of clauses ───────────────────────────────────────────────────── */

function ScopeRack({
  granted,
  onToggle,
  needs,
  missing,
}: {
  granted: Set<ScopeId>;
  onToggle: (id: ScopeId) => void;
  needs?: ScopeId[];
  missing?: ScopeId[];
}) {
  return (
    <fieldset className="rr-rack">
      <legend className="rr-rack__legend">What it may read</legend>
      <p className="rr-rack__hint">
        Take one away and file the request again — the room answers with less, or
        stops at the gate.
      </p>
      <div className="rr-rack__list">
        {SCOPES.map((s) => {
          const on = granted.has(s.id);
          const needed = needs?.includes(s.id) ?? false;
          const blocking = missing?.includes(s.id) ?? false;
          return (
            <label
              key={s.id}
              className={cn(
                "rr-clause",
                on && "is-on",
                needed && "is-needed",
                blocking && "is-blocking"
              )}
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(s.id)}
                className="rr-clause__box"
              />
              <span className="rr-clause__tick" aria-hidden>
                {on ? "✓" : ""}
              </span>
              <span className="rr-clause__body">
                <span className="rr-clause__top">
                  <span className="rr-clause__label">{s.label}</span>
                  <code className="rr-clause__id">{s.id}</code>
                </span>
                <span className="rr-clause__clause">
                  {s.clause}
                  {blocking && <span className="rr-clause__flag"> · required</span>}
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/* ── The passage: six apertures, stamped as the request clears them ────────── */

function Passage({
  outcome,
  reached,
  travelling,
  engineer,
}: {
  outcome: Outcome | null;
  reached: number;
  travelling: boolean;
  engineer: boolean;
}) {
  return (
    <div className={cn("rr-passage", travelling && "is-live")}>
      <div className="rr-passage__head">
        <span className="rr-passage__title">The request&rsquo;s passage</span>
        {outcome && (
          <span className="rr-passage__state" aria-hidden>
            {travelling ? "in transit" : outcome.denied ? "stopped" : "returned"}
          </span>
        )}
      </div>

      {/* the rail the request travels — lit only while something is moving */}
      <ol className="rr-track">
        {STATIONS.map((st, i) => {
          const cleared = outcome !== null && reached >= i && !(outcome.denied && i > GATE_INDEX);
          const stoppedHere = outcome?.denied === true && i === GATE_INDEX && reached >= i;
          const unreachable = outcome?.denied === true && i > GATE_INDEX;
          return (
            <li
              key={st.id}
              className={cn(
                "rr-stop",
                cleared && !stoppedHere && "is-cleared",
                stoppedHere && "is-stopped",
                unreachable && "is-dark"
              )}
            >
              <span className="rr-stop__iris" aria-hidden>
                <span className="rr-stop__leaf" />
                <span className="rr-stop__leaf" />
              </span>
              <span className="rr-stop__body">
                <span className="rr-stop__name">{st.name}</span>
                <span className="rr-stop__plain">
                  {engineer ? st.mechanism : st.plain}
                </span>
                {engineer && <code className="rr-stop__evidence">{st.evidence}</code>}
              </span>
              <span className="rr-stop__mark">
                {stoppedHere ? (
                  <span className="rr-mark rr-mark--deny">Denied</span>
                ) : cleared ? (
                  <span className="rr-mark rr-mark--ok">{st.stamp}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* ── The one honest sentence about writing ─────────────────────────────────── */

function WriteTruth() {
  return (
    <div className="rr-write">
      <p className="rr-write__head">{WRITE_TRUTH.headline}</p>
      <p className="rr-write__body">{WRITE_TRUTH.body}</p>
    </div>
  );
}
