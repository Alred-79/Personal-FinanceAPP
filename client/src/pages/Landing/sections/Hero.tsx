import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import { ReadOnlyBadge } from "@/components/custom/Trust/ReadOnlyBadge";
import { AnchorLink, EASE } from "../shared";
import { DecisionLab } from "./DecisionLab";

/** The new front door: one promise, one working decision, no occupation gate. */
export function Hero() {
  const reduce = useReducedMotion();

  return (
    <header className="decision-hero" id="top">
      <motion.div
        className="decision-hero__copy"
        initial={reduce ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.72, ease: EASE }}
      >
        <p className="decision-hero__institution">Independent personal money control</p>
        <h1>Know what&rsquo;s safe. Test what happens next.</h1>
        <p className="decision-hero__lede">
          The Ledger reads across your accounts, bills, income, and goals to show
          what you can spend now, what could derail it, and how a decision changes
          the outcome.
        </p>

        <div className="decision-hero__actions">
          <Link to="/login" className="decision-primary press">
            Open your ledger
          </Link>
          <AnchorLink to="#how-it-works" className="decision-secondary press">
            See how the answer is made
          </AnchorLink>
        </div>

        <div className="decision-hero__assurances">
          <ReadOnlyBadge label="Read-only by default" />
          <span>No card required</span>
          <span>No product kickbacks</span>
        </div>
      </motion.div>

      <motion.div
        className="decision-hero__instrument"
        initial={reduce ? false : { opacity: 0, x: 28, rotate: 0.6 }}
        animate={{ opacity: 1, x: 0, rotate: 0 }}
        transition={{ duration: 0.82, ease: EASE, delay: 0.1 }}
      >
        <DecisionLab />
      </motion.div>
    </header>
  );
}
