import { Seal } from "@/components/engraving/Seal";
import { Rise } from "../shared";
import { SecurityScene } from "./securityVisuals";

/** A single verifiable guarantee — title + plain-language body (the picture is by index). */
type Claim = { title: string; body: string };

/**
 * Each claim below is true of the product as built — read-only MCP vault,
 * confirm-then-write tokens, deterministic PII scrubbing, integer-cent money,
 * refresh-token family revocation. This section replaces the old fabricated
 * stats: honest engineering guarantees, not invented numbers. The order matches
 * the bespoke scenes in securityVisuals.tsx (SecurityScene index).
 */
const CLAIMS: Claim[] = [
  {
    title: "Read-only by default",
    body: "Connect only what you choose. The default connection can read the accounts you authorize, but it cannot quietly move money behind the page.",
  },
  {
    title: "It proposes. You confirm.",
    body: "The assistant drafts a change and shows the before-and-after difference. Nothing becomes real until you explicitly confirm it.",
  },
  {
    title: "Sensitive details are removed first",
    body: "Before data reaches the assistant, a deterministic filter strips SSNs, emails, and card or account numbers. The safety step does not depend on the model noticing them.",
  },
  {
    title: "The arithmetic stays exact",
    body: "Every amount is stored as whole cents and calculated outside the model, so $10.99 never quietly drifts after several transactions.",
  },
  {
    title: "Reused sessions shut themselves down",
    body: "If an already-rotated session credential appears again, the entire session family is revoked. A replayed credential locks itself out.",
  },
  {
    title: "We never sell your data",
    body: "There is no ad model and no broker on the other end. Your ledger exists to help you make decisions, not to sell you a financial product.",
  },
];

/** The Vault — the product's real security guarantees, on the dark side. */
export function Security() {
  return (
    <section id="vault" className="mt-28">
      <Rise className="mx-auto max-w-[44rem] text-center">
        <div className="mb-5 flex justify-center">
          <div className="vault-seal-spin">
            <Seal size={72} label="Sealed · Audited · Sealed · Audited" />
          </div>
        </div>
        <p className="dept-label">The Vault · How control is kept</p>
        <h2 className="mt-2 font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}>
          It shows its work. It never takes the wheel.
        </h2>
        <p className="mt-3 text-[1.02rem] text-muted-foreground">
          A useful money assistant makes its evidence, uncertainty, and boundaries
          visible. These are not promises pasted onto the page — they are how the
          product is wired.
        </p>
      </Rise>

      <div className="vault-wall mt-10 p-3 sm:p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {CLAIMS.map((c, i) => (
            <Rise key={c.title} delay={(i % 3) * 0.06}>
              <article className="vault-box group h-full p-5">
                <span className="vault-box__seam" aria-hidden />
                <div className="flex items-center justify-between">
                  <span className="vault-box__serial font-mono text-[0.66rem] tracking-[0.22em]">No. 0{i + 1}</span>
                  <svg className="vault-box__dial" width="28" height="28" viewBox="0 0 40 40" fill="none" stroke="currentColor" aria-hidden="true">
                    <circle cx="20" cy="20" r="16" strokeWidth="1.4" strokeDasharray="1 3.6" />
                    <circle cx="20" cy="20" r="11" strokeWidth="1" opacity="0.5" />
                    <line x1="20" y1="20" x2="20" y2="6" strokeWidth="1.8" strokeLinecap="round" />
                    <circle cx="20" cy="20" r="1.8" fill="currentColor" stroke="none" />
                  </svg>
                </div>
                <div className="vault-box__stage">
                  <SecurityScene index={i} />
                </div>
                <h3 className="font-display text-[1.1rem] font-semibold leading-snug">{c.title}</h3>
                <p className="mt-2 text-[0.9rem] leading-relaxed text-muted-foreground">{c.body}</p>
              </article>
            </Rise>
          ))}
        </div>
      </div>
    </section>
  );
}
