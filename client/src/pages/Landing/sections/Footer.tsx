import { AnchorLink, LedgerSeal } from "../shared";

export function Footer() {
  return (
    <footer className="decision-footer">
      <div className="decision-footer__inner">
        <AnchorLink to="#top" className="decision-footer__brand">
          <LedgerSeal size={30} />
          <span>The Ledger</span>
        </AnchorLink>
        <p>Independent personal money control · Est. MMXXVI</p>
        <nav aria-label="Footer">
          <AnchorLink to="#how-it-works">How it works</AnchorLink>
          <AnchorLink to="#work-money">Work Money</AnchorLink>
          <AnchorLink to="#trust">Trust</AnchorLink>
        </nav>
      </div>
    </footer>
  );
}
