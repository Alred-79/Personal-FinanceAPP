import { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  /** Optional actions rendered on the right (e.g. a "New" button). */
  actions?: ReactNode;
}

/** Consistent page title block used at the top of each page's content. */
export default function PageHeader({
  title,
  description,
  actions,
}: PageHeaderProps) {
  return (
    <div className="mb-6 flex flex-col gap-3 border-b-4 border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1">
        <h2 className="font-mono text-3xl font-bold uppercase tracking-tight md:text-4xl flex items-center gap-2">
          <span className="text-primary select-none">&gt;_</span>
          {title}
          <span className="text-primary animate-terminal-blink ml-1">▋</span>
        </h2>
        {description && (
          <p className="text-sm font-mono text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
