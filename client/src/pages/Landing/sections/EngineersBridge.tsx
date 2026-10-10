import { Link } from "react-router-dom";
import { Rise } from "../shared";

const PROOFS = [
  {
    title: "Your own AI, read-only",
    body: "Connect an MCP-compatible assistant, choose exactly what it can read, and revoke it any time.",
  },
  {
    title: "Every claim cites its test",
    body: "Each security promise links to the file that enforces it and the test that proves it.",
  },
  {
    title: "Honest about the gaps",
    body: "Controls that ship switched off, or need setup to protect anything, are labelled that way.",
  },
];

/**
 * The hand-off from the consumer page to "How it's built". The Reading Room and
 * the Specimen Sheet used to sit here in full; they now live on their own page,
 * so this band names what is there and links to it.
 */
export function EngineersBridge() {
  return (
    <section id="agents" className="mt-28">
      <Rise>
        <div className="grid gap-10 border-y border-rule-strong/40 py-12 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:gap-16">
          <div className="text-center lg:text-left">
            <p className="dept-label">For engineers, and the curious</p>
            <h2 className="mt-2 text-balance font-display font-semibold leading-[1.1]" style={{ fontSize: "clamp(1.7rem,4vw,2.5rem)" }}>
              Don&rsquo;t take our word for it.
            </h2>
            <p className="mx-auto mt-3 max-w-[30rem] text-pretty text-muted-foreground lg:mx-0">
              See what an AI assistant can and can&rsquo;t read, walk one request
              through every check, and open the code behind each claim.
            </p>
            <Link
              to="/how-its-built"
              className="press mt-6 inline-block border border-rule-strong/60 px-6 py-3 text-[0.86rem] font-semibold uppercase tracking-[0.04em]"
            >
              How it&rsquo;s built &rarr;
            </Link>
          </div>
          <ol className="grid content-center gap-0">
            {PROOFS.map((p) => (
              <li key={p.title} className="border-b border-rule-strong/25 py-4 last:border-b-0">
                <h3 className="font-display text-[1.08rem] font-semibold">{p.title}</h3>
                <p className="mt-1 text-[0.92rem] leading-relaxed text-muted-foreground">{p.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </Rise>
    </section>
  );
}
