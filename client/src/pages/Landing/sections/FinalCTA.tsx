import { Link } from "react-router-dom";
import { LedgerSeal, Rise } from "../shared";
import { Magnetic } from "../effects/Magnetic";
import { DemoLink } from "../demo";

/** Final call to action — the framed seal plate. */
export function FinalCTA() {
  return (
    <Rise className="mt-28">
      <section className="security-window relative overflow-hidden px-6 py-16 text-center sm:px-16">
        <div className="relative flex flex-col items-center">
          <LedgerSeal size={48} className="mb-5" />
          <h2 className="text-balance font-display font-semibold" style={{ fontSize: "clamp(2rem,5vw,3.4rem)" }}>
            Find out what&rsquo;s actually safe to spend.
          </h2>
          <p className="mx-auto mt-3 max-w-[34rem] text-pretty text-muted-foreground">
            Walk through a full sample ledger in the demo, no signup needed. Or open
            your own and connect only the accounts you choose.
          </p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <Magnetic>
              <DemoLink className="press inline-block bg-primary px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground">
                Try the demo
              </DemoLink>
            </Magnetic>
            <Link
              to="/login"
              className="press border border-rule-strong/60 px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em]"
            >
              Open your ledger
            </Link>
          </div>
        </div>
      </section>
    </Rise>
  );
}
