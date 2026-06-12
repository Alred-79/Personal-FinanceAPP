import { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SectionRuleProps {
  children: ReactNode;
  /** Show the aldus leaf fleurons either side of the label. */
  fleuron?: boolean;
  className?: string;
}

/** Classic ledger section divider:  ———— ❦ TITLE ❦ ————  */
export function SectionRule({
  children,
  fleuron = true,
  className,
}: SectionRuleProps) {
  return (
    <div className={cn("section-rule", className)} role="presentation">
      {fleuron && (
        <span className="select-none text-xs text-gold" aria-hidden="true">
          ❦
        </span>
      )}
      <span className="dept-label whitespace-nowrap">{children}</span>
      {fleuron && (
        <span className="select-none text-xs text-gold" aria-hidden="true">
          ❦
        </span>
      )}
    </div>
  );
}
