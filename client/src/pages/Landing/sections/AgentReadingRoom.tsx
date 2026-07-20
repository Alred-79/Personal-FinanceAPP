import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Rise } from "../shared";
import { Magnetic } from "../effects/Magnetic";
import { landingScrollTo } from "../hooks/useLenis";
import { ReadingRoomDesk } from "./agents/ReadingRoomDesk";

/**
 * THE AGENT READING ROOM
 *
 * The product's MCP surface, made physical. Rather than draw the usual
 * nodes-and-edges architecture diagram, the section puts the visitor at the
 * counter of a dim archival vault: you hand over a written request, it travels
 * through apertures that check it, and it comes back as a stamped docket with a
 * receipt. Every station is a real mechanism (server/src/mcp/) — the scope
 * strings, the policy gate, the read-only vault that always rolls back, the
 * hash-only audit row — so the demonstration is the architecture, not a picture
 * of it.
 *
 * The whole thing is click-driven and deterministic: an example ledger, never a
 * live API call, and never a suggestion that an agent can move money.
 */
export function AgentReadingRoom() {
  const deskRef = useRef<HTMLDivElement>(null);
  const [engineer, setEngineer] = useState(false);

  // "See how access works" doesn't scroll to a different section — it turns the
  // apparatus itself over to show its workings.
  const showWorkings = useCallback(() => {
    setEngineer(true);
    landingScrollTo("#agents");
  }, []);

  return (
    <section id="agents" className="mt-28">
      <Rise className="mx-auto max-w-[46rem] text-center">
        <p className="dept-label">The Reading Room · Agent access</p>
        <h2
          className="mt-2 text-balance font-display font-semibold"
          style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}
        >
          Your AI can understand the whole ledger.
        </h2>
        {/* "every request your key makes" — not "every request". Anonymous
            denials are never persisted (mcp_audit_store.persist returns early
            when user_id is None, because an unknown-key flood has nobody to
            attribute it to), so an unresolvable key exists only in process
            logs. The qualified wording is the exact one. */}
        <p className="mx-auto mt-3 max-w-[38rem] text-pretty text-[1.02rem] leading-relaxed text-muted-foreground">
          Connect an MCP-compatible assistant to your accounts, transactions, budgets,
          goals, forecasts, and scenarios. Choose what it can read, inspect every
          request your key makes, and revoke access anytime.
        </p>

        <div className="mt-5 flex justify-center">
          <AvailabilityChip />
        </div>

        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Magnetic>
            <Link
              to="/login?next=%2Fsettings%3Ftab%3Dagent-keys"
              className="press inline-block bg-primary px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground"
            >
              Connect your AI
            </Link>
          </Magnetic>
          <button
            type="button"
            onClick={showWorkings}
            className="press border border-rule-strong/60 px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em]"
          >
            See how access works
          </button>
        </div>

        <p className="mx-auto mt-4 max-w-[30rem] text-[0.76rem] leading-relaxed text-muted-foreground/80">
          Your chosen AI provider receives the information you authorize.
        </p>
      </Rise>

      <Rise delay={0.08}>
        <div ref={deskRef}>
          <ReadingRoomDesk engineer={engineer} onEngineerChange={setEngineer} />
        </div>
      </Rise>
    </section>
  );
}

/**
 * The availability seal — a struck brass token, not a "beta" pill. MCP access is
 * shipped and mounted; the chip should read as a stamped fact.
 */
function AvailabilityChip() {
  return (
    <span className="rr-chip">
      <span className="rr-chip__pip" aria-hidden />
      Available now via MCP
    </span>
  );
}
