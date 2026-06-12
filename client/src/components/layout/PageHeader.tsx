import { ReactNode } from "react";
import { GuillocheBand } from "@/components/engraving/Guilloche";

interface PageHeaderProps {
  title: string;
  description?: string;
  /** Optional actions rendered on the right (e.g. a "New" button). */
  actions?: ReactNode;
  /** Tiny line under the title — a form number, edition, etc. */
  reference?: string;
}

/**
 * The masthead of a printed financial document: a smallcaps department line,
 * an engraved serif title, and a woven guilloché band ruling it off from the
 * page body. Every page opens like an official form.
 */
export default function PageHeader({
  title,
  description,
  actions,
  reference,
}: PageHeaderProps) {
  return (
    <header className="mb-8 animate-rise-in">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1.5">
          <p className="dept-label flex items-center gap-2">
            <span className="text-gold">§</span>
            Department of Personal Accounts
            {reference && (
              <span className="text-muted-foreground/60 normal-case tracking-normal">
                · {reference}
              </span>
            )}
          </p>
          <h1 className="font-display text-4xl font-semibold leading-[0.95] tracking-tight md:text-5xl">
            {title}
          </h1>
          {description && (
            <p className="max-w-xl font-sans text-sm text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>

      <div className="mt-5 text-gold/70">
        <GuillocheBand height={18} waves={4} seed={title.length + 2} />
      </div>
    </header>
  );
}
