import { cn } from "@/lib/utils";
import { SCOPES, type Request, type ScopeId } from "./readingRoomData";

type Outcome = {
  request: Request;
  missing: ScopeId[];
  denied: boolean;
  finalIndex: number;
};

/**
 * What comes back over the counter: a filed docket, and beneath it the receipt
 * the room keeps for itself. Both mirror the real thing — the docket's figures
 * stay sober (no glow, no decoration on money), and the receipt carries exactly
 * the fields the audit log stores: resource, decision, latency, and a truncated
 * fingerprint of the parameters.
 */
export function AnswerDocket({
  outcome,
  settled,
  engineer,
  onGrant,
}: {
  outcome: Outcome | null;
  settled: boolean;
  engineer: boolean;
  onGrant: (ids: ScopeId[]) => void;
}) {
  return (
    <div className="rr-docket" aria-live="polite">
      {!outcome ? (
        <Waiting />
      ) : !settled ? (
        <InTransit />
      ) : outcome.denied ? (
        <Denied outcome={outcome} onGrant={onGrant} engineer={engineer} />
      ) : (
        <Filed outcome={outcome} engineer={engineer} />
      )}
    </div>
  );
}

function Waiting() {
  return (
    <div className="rr-docket__empty">
      <p className="rr-docket__emptyhead">The counter is open.</p>
      <p className="rr-docket__emptybody">
        File one of the three requests above and watch it cross the apertures.
      </p>
    </div>
  );
}

function InTransit() {
  return (
    <div className="rr-docket__empty">
      <p className="rr-docket__emptyhead">Carrying the request…</p>
    </div>
  );
}

/* ── Cleared: the answer, filed ────────────────────────────────────────────── */

function Filed({ outcome, engineer }: { outcome: Outcome; engineer: boolean }) {
  const { request } = outcome;
  return (
    <article className="rr-filed">
      <header className="rr-filed__head">
        <p className="rr-filed__q">{request.question}</p>
        <span className="rr-filed__seal" aria-hidden>
          Filed
        </span>
      </header>

      <p className="rr-filed__verdict">{request.verdict}</p>

      <dl className="rr-filed__lines">
        {request.lines.map((l) => (
          <div key={l.label} className="rr-filed__line">
            <dt>{l.label}</dt>
            <dd
              className={cn(
                "figure",
                l.ink === "credit" && "ink-credit",
                l.ink === "debit" && "ink-debit"
              )}
            >
              {l.value}
            </dd>
          </div>
        ))}
      </dl>

      <p className="rr-filed__basis">{request.basis}</p>

      {engineer && (
        <p className="rr-filed__tools">
          <span>Tools called</span>
          {request.tools.map((t) => (
            <code key={t}>{t}</code>
          ))}
        </p>
      )}

      <Receipt outcome={outcome} decision="allow" />
    </article>
  );
}

/* ── Stopped: the gate refused it ──────────────────────────────────────────── */

function Denied({
  outcome,
  onGrant,
  engineer,
}: {
  outcome: Outcome;
  onGrant: (ids: ScopeId[]) => void;
  engineer: boolean;
}) {
  const names = outcome.missing.map(
    (id) => SCOPES.find((s) => s.id === id)?.label ?? id
  );
  return (
    <article className="rr-filed rr-filed--denied">
      <header className="rr-filed__head">
        <p className="rr-filed__q">{outcome.request.question}</p>
        <span className="rr-filed__seal rr-filed__seal--deny" aria-hidden>
          Denied
        </span>
      </header>

      <p className="rr-filed__verdict">Denied · scope required</p>

      <p className="rr-filed__basis">
        The request never reached your data. It asked for{" "}
        {outcome.missing.map((id, i) => (
          <span key={id}>
            {i > 0 && (i === outcome.missing.length - 1 ? " and " : ", ")}
            <code className="rr-filed__scope">{id}</code>
          </span>
        ))}
        , which {outcome.missing.length > 1 ? "are" : "is"} not on this key. The gate
        refuses what it cannot narrow to — it has no way to widen a key on the
        assistant&rsquo;s behalf.
      </p>

      {engineer && (
        <p className="rr-filed__tools">
          <span>Refused before</span>
          {outcome.request.tools.map((t) => (
            <code key={t}>{t}</code>
          ))}
        </p>
      )}

      <button
        type="button"
        className="rr-grant"
        onClick={() => onGrant(outcome.missing)}
      >
        Grant {names.join(" & ")} and file it again
      </button>

      <Receipt outcome={outcome} decision="deny" />
    </article>
  );
}

/* ── The receipt the room keeps ────────────────────────────────────────────── */

function Receipt({
  outcome,
  decision,
}: {
  outcome: Outcome;
  decision: "allow" | "deny";
}) {
  const { request } = outcome;
  return (
    <div className="rr-receipt">
      <div className="rr-receipt__row">
        <code className="rr-receipt__resource">{request.resource}</code>
        <span
          className={cn(
            "rr-receipt__decision",
            decision === "deny" && "rr-receipt__decision--deny"
          )}
        >
          {decision === "allow" ? "Allow" : "Deny"}
        </span>
        <span className="rr-receipt__latency">
          {decision === "allow" ? request.latencyMs : 3} ms
        </span>
        <code className="rr-receipt__hash">{request.paramsHash}…</code>
        <span className="rr-receipt__when">just now</span>
      </div>
      <p className="rr-receipt__foot">
        Inputs are hashed, never stored raw · the vault opens read-only and always
        rolls back
      </p>
    </div>
  );
}
