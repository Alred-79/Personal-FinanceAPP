import { motion } from "motion/react";
import { Feather, X } from "lucide-react";
import styles from "./ClerkTicket.module.css";

interface ClerkTicketProps {
  label: string;
  /** Click the slip → open the window with the suggestion pre-filled. */
  onActivate: () => void;
  /** When present, a ✕ that silences auto-nudges for the session (auto only). */
  onDismiss?: () => void;
  reduced?: boolean;
}

/**
 * The Clerk's margin-note ticket: a small engraved paper slip that unfurls from
 * the launcher with a contextual offer ("Want to describe a rule?"). It is a
 * status region (announced politely, never steals focus) and a button — clicking
 * pre-fills the prompt, it never sends on its own.
 */
export function ClerkTicket({ label, onActivate, onDismiss, reduced }: ClerkTicketProps) {
  return (
    <motion.div
      className={styles.ticket}
      role="status"
      initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.85, y: 6 }}
      animate={reduced ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.9, y: 4 }}
      transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
    >
      <button type="button" className={styles.slip} onClick={onActivate}>
        <Feather className={styles.quill} aria-hidden />
        <span className={styles.label}>{label}</span>
      </button>
      {onDismiss && (
        <button
          type="button"
          className={styles.dismiss}
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          aria-label="Not now — don't suggest again this visit"
        >
          <X className="h-3 w-3" />
        </button>
      )}
      <span className={styles.tail} aria-hidden />
    </motion.div>
  );
}
