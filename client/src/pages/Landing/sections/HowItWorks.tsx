const LEDGER_ROWS = [
  { label: "Across your accounts", value: "+$3,500", tone: "credit" },
  { label: "Income before the horizon", value: "+$1,800", tone: "credit" },
  { label: "Bills and minimums", value: "−$1,850", tone: "debit" },
  { label: "Goal commitments and pace", value: "−$1,900", tone: "debit" },
  { label: "Cash buffer you chose", value: "−$700", tone: "debit" },
] as const;

export function HowItWorks() {
  return (
    <section className="answer-section" id="how-it-works" aria-labelledby="answer-title">
      <div className="answer-section__copy">
        <h2 id="answer-title">A balance is only the beginning.</h2>
        <p>
          Your bank can tell you what is there. The Ledger accounts for what is
          already spoken for, models the uncertain part, and keeps every assumption
          close enough to inspect.
        </p>

        <ol className="answer-flow">
          <li>
            <span>1</span>
            <div><strong>Read the whole picture</strong><small>Connected accounts, imports, bills, income, goals.</small></div>
          </li>
          <li>
            <span>2</span>
            <div><strong>Model the range</strong><small>Known cash flow plus the variation in how you actually spend.</small></div>
          </li>
          <li>
            <span>3</span>
            <div><strong>Show the decision</strong><small>One answer, its range, and the rows that produced it.</small></div>
          </li>
        </ol>
      </div>

      <div className="answer-ledger" aria-label="Illustrative Safe-to-Spend calculation">
        <div className="answer-ledger__head">
          <span>Safe-to-Spend memorandum</span>
          <span>No. STS-0030</span>
        </div>
        <div className="answer-ledger__body">
          {LEDGER_ROWS.map((row) => (
            <div className="answer-ledger__row" key={row.label}>
              <span>{row.label}</span>
              <strong className={row.tone === "credit" ? "ink-credit" : "ink-debit"}>
                {row.value}
              </strong>
            </div>
          ))}
          <div className="answer-ledger__total">
            <span>Safe until the next income date</span>
            <strong>$850</strong>
          </div>
          <p>
            This is a worked example. In your ledger, every line links back to its
            source and freshness.
          </p>
        </div>
      </div>
    </section>
  );
}
