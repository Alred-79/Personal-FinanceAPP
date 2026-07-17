const LIFECYCLE = ["Reads", "Calculates", "Cites", "Proposes", "You confirm", "Verifies"];

const PROOFS = [
  {
    title: "Read-only by default",
    body: "The connection can read the accounts you authorize. The assistant cannot quietly move money behind the page.",
  },
  {
    title: "The arithmetic stays outside the model",
    body: "Deterministic tools compute the figures. The assistant explains them and links back to the underlying rows.",
  },
  {
    title: "Every action has a human boundary",
    body: "A proposal becomes real only after an explicit confirmation, with a visible before-and-after record.",
  },
];

export function Trust() {
  return (
    <section className="trust-section" id="trust" aria-labelledby="trust-title">
      <div className="trust-section__inner">
        <div className="trust-section__heading">
          <span className="trust-section__seal" aria-hidden>£</span>
          <div>
            <h2 id="trust-title">It shows its work. It never takes the wheel.</h2>
            <p>
              The point of a money assistant is not to sound certain. It is to make
              the evidence, the uncertainty, and the boundary of every action visible.
            </p>
          </div>
        </div>

        <ol className="trust-flow" aria-label="How a Ledger action works">
          {LIFECYCLE.map((step, index) => (
            <li key={step}>
              <span>{index + 1}</span>
              <strong>{step}</strong>
            </li>
          ))}
        </ol>

        <div className="trust-proofs">
          {PROOFS.map((proof) => (
            <article key={proof.title}>
              <h3>{proof.title}</h3>
              <p>{proof.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
