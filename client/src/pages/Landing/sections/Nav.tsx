import { Link } from "react-router-dom";
import { AnchorLink, LedgerSeal } from "../shared";

export function Nav() {
  return (
    <nav className="decision-nav" aria-label="Primary">
      <div className="decision-nav__inner">
        <AnchorLink className="decision-nav__brand" to="#top">
          <LedgerSeal size={36} />
          <span>The Ledger</span>
        </AnchorLink>

        <div className="decision-nav__links">
          <AnchorLink to="#how-it-works">How it works</AnchorLink>
          <AnchorLink to="#work-money">Work Money</AnchorLink>
          <AnchorLink to="#trust">Trust</AnchorLink>
        </div>

        <Link className="decision-nav__cta press" to="/login">
          Open your ledger
        </Link>
      </div>
    </nav>
  );
}
