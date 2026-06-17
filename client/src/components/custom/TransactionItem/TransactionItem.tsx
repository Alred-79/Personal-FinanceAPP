import { Transaction } from "@/types";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { categoryIcon } from "@/lib/categoryIcon";
import { categoryColor } from "@/lib/format";
import { useIsMobile } from "@/hooks/responsive";
import { useStore } from "@/store/store";
import { TaxTagControl } from "@/components/custom/TaxTagBadge/TaxTagControl";

/**
 * A single posting in the ledger: an engraved category glyph, the entry's
 * description and date, and the amount set in red (debit) or green (credit)
 * ink, right-aligned with a manicule that points on hover. The whole thing
 * sits on a hairline ledger rule.
 */
function TransactionItem({
  transaction,
  onDelete,
  style,
}: {
  transaction: Transaction;
  onDelete: (() => void) | null;
  style?: React.CSSProperties;
}) {
  const isMobile = useIsMobile();
  const [isSelected, setIsSelected] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const taxEnabled = useStore((s) => s.taxFeaturesEnabled);
  const Icon = categoryIcon(transaction.category);
  const isIncome = transaction.type === "income";
  const tint = transaction.backgroundColor || categoryColor(transaction.category);

  const showDelete =
    onDelete !== null && (isMobile ? isSelected : false);

  return (
    <div className="border-b border-rule/0">
    <div
      style={style}
      className="ledger-row group flex items-center gap-3 px-1.5 py-2.5"
      onClick={() => (isMobile ? setIsSelected((s) => !s) : setExpanded((e) => !e))}
    >
      <span
        className="grid h-9 w-9 shrink-0 place-items-center border border-rule-strong/40 bg-card"
        style={{ color: tint }}
      >
        <Icon className="h-[18px] w-[18px]" />
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate font-sans text-[15px] font-medium text-foreground">
          {transaction.title}
        </p>
        <p className="font-mono text-[11px] text-muted-foreground">
          {transaction.date}
          <span className="mx-1.5 text-rule-strong/50">·</span>
          <span className="uppercase tracking-[0.1em]">{transaction.category}</span>
        </p>
      </div>

      {taxEnabled && (
        <span className="mr-1 shrink-0" onClick={(e) => e.stopPropagation()}>
          <TaxTagControl txType={transaction.type} txId={transaction.id} />
        </span>
      )}

      <span className="manicule mr-1 hidden text-sm sm:inline" aria-hidden="true">
        ☞
      </span>

      <p
        className={`ledger-figures shrink-0 text-base font-medium tabular-nums ${
          isIncome ? "ink-credit" : "ink-debit"
        }`}
      >
        {isIncome ? "+" : "−"}${Math.abs(transaction.amount).toFixed(2)}
      </p>

      {onDelete !== null && (
        <button
          aria-label="Delete entry"
          className={`grid h-7 w-7 shrink-0 place-items-center text-muted-foreground transition-all hover:text-debit ${
            showDelete ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          }`}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
            if (isMobile) setIsSelected(false);
          }}
        >
          <Trash2 className="h-[15px] w-[15px]" />
        </button>
      )}
    </div>

      {/* frontend-elevation: desktop click expands a detail strip */}
      <AnimatePresence initial={false}>
        {expanded && !isMobile && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            style={{ overflow: "hidden" }}
          >
            <div className="grid grid-cols-3 gap-2 px-12 pb-2.5 pt-0.5 font-mono text-[11px] text-muted-foreground">
              <span>
                <span className="uppercase tracking-[0.12em] text-rule-strong/70">Type</span>
                <br />
                {transaction.type}
              </span>
              <span>
                <span className="uppercase tracking-[0.12em] text-rule-strong/70">Category</span>
                <br />
                {transaction.category}
              </span>
              <span className="text-right">
                <span className="uppercase tracking-[0.12em] text-rule-strong/70">Amount</span>
                <br />
                <span className={isIncome ? "ink-credit" : "ink-debit"}>
                  {isIncome ? "+" : "−"}${Math.abs(transaction.amount).toFixed(2)}
                </span>
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default TransactionItem;
