const CORE_ITEMS = [
  "Safe-to-Spend with an explainable breakdown",
  "Modeled cash-flow ranges and shortfall odds",
  "What-if decisions before they touch the ledger",
  "Goals, recurring charges, imports, and reconciliation",
];

const WORK_ITEMS = [
  "Income stability across uneven months",
  "A tax-reserve target you fund in your own bank",
  "Quarterly estimate reminders and deduction organization",
];

function CheckList({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map((item) => (
        <li key={item}><span aria-hidden>✓</span>{item}</li>
      ))}
    </ul>
  );
}

export function Modes() {
  return (
    <section className="modes-section" id="work-money" aria-labelledby="modes-title">
      <div className="modes-section__heading">
        <h2 id="modes-title">Personal by default. Specialized when needed.</h2>
        <p>
          Start with one calm personal ledger. Add the working-life layer only if
          income timing and taxes are part of the problem.
        </p>
      </div>

      <div className="modes-ledger">
        <article className="modes-ledger__core">
          <div className="modes-ledger__label">
            <span>Core Ledger</span>
            <small>For everyday personal money</small>
          </div>
          <h3>Everything needed to make the next decision clearly.</h3>
          <CheckList items={CORE_ITEMS} />
        </article>

        <article className="modes-ledger__work">
          <div className="modes-ledger__label">
            <span>Work Money</span>
            <small>Optional specialization</small>
          </div>
          <h3>For freelance, contract, commission, and mixed income.</h3>
          <CheckList items={WORK_ITEMS} />
          <p className="modes-ledger__honesty">
            The Ledger calculates, recommends, and tracks. It never claims to hold
            your tax money or smooth your paycheck for you.
          </p>
        </article>
      </div>

      <div className="focus-note">
        <span className="focus-note__mark" aria-hidden>¢</span>
        <div>
          <strong>Focus Mode stays optional.</strong>
          <p>
            Turn debt and goal progress into a low-shame game when that helps. It
            rewards real progress—never spending—and it never touches real figures.
          </p>
        </div>
      </div>
    </section>
  );
}
