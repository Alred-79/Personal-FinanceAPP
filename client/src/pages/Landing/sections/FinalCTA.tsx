import { Link } from "react-router-dom";
import { GuillocheBand } from "@/components/engraving/Guilloche";

export function FinalCTA() {
  return (
    <section className="final-decision" aria-labelledby="final-decision-title">
      <GuillocheBand height={22} waves={5} seed={18} />
      <div className="final-decision__content">
        <div>
          <h2 id="final-decision-title">Bring your real numbers into view.</h2>
          <p>
            Open a ledger, connect only what you choose, and see the first answer
            before you change a thing.
          </p>
        </div>
        <Link to="/login" className="decision-primary press">
          Open your ledger
        </Link>
      </div>
      <div className="final-decision__assurances">
        <span>Read-only by default</span>
        <span>No card required</span>
        <span>Your data is not the product</span>
      </div>
    </section>
  );
}
