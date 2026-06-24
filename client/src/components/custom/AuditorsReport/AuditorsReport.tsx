import { FC } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCheck } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SectionRule } from "@/components/engraving/SectionRule";
import { EmptyState } from "@/components/engraving/EmptyState";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { useStore } from "@/store/store";
import type { Notification } from "@/types";
import {
  metaFor,
  isProposal,
  groupFor,
  relTime,
  TONE_TEXT,
  TONE_EDGE,
  NOTICE_GROUPS,
  type NoticeGroup,
} from "@/lib/notices";
import ProposalApprove from "./ProposalApprove";

/**
 * The Auditor's Report — a roomier ledger of the nightly auditor's findings,
 * grouped by kind, each with its deep-link or an inline one-tap Approve. Opened
 * from the bell's "Open full report". The bell is the glance; this is the desk.
 */
const AuditorsReport: FC<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
}> = ({ open, onOpenChange }) => {
  const {
    notifications,
    unreadCount,
    markNotificationRead,
    markAllNotificationsRead,
  } = useStore();
  const navigate = useNavigate();

  const sorted = [...notifications].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? "")
  );

  const byGroup = new Map<NoticeGroup, Notification[]>();
  for (const n of sorted) {
    const g = groupFor(n.type);
    const list = byGroup.get(g);
    if (list) list.push(n);
    else byGroup.set(g, [n]);
  }

  const go = (n: Notification) => {
    if (!n.read) markNotificationRead(n.id);
    const to = metaFor(n.type).to;
    if (to) {
      onOpenChange(false);
      navigate(to);
    }
  };

  const Finding = ({ n }: { n: Notification }) => {
    const meta = metaFor(n.type);
    const Icon = meta.icon;
    const proposal = isProposal(n.type);
    return (
      <RevealItem>
        <div
          className={`ledger-row border-l-2 px-4 py-3 ${TONE_EDGE[meta.tone]} ${
            n.read ? "opacity-60" : ""
          }`}
        >
          <div className="flex items-start gap-2.5">
            <Icon size={14} className={`mt-0.5 shrink-0 ${TONE_TEXT[meta.tone]}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-sans text-sm font-semibold text-foreground">
                  {n.title}
                </span>
                {n.created_at && (
                  <span className="shrink-0 font-mono text-[10px] text-muted-foreground/60">
                    {relTime(n.created_at)}
                  </span>
                )}
              </div>
              <p className="mt-0.5 font-sans text-xs text-muted-foreground">
                {n.message}
              </p>
              {proposal ? (
                <ProposalApprove
                  notificationId={n.id}
                  label={meta.verb ?? "Approve"}
                />
              ) : (
                meta.to &&
                meta.verb && (
                  <button
                    type="button"
                    onClick={() => go(n)}
                    className="mt-1 inline-block font-sans text-[10px] uppercase tracking-[0.14em] text-gold transition-colors hover:text-foreground"
                  >
                    {meta.verb} →
                  </button>
                )
              )}
            </div>
            {!n.read && (
              <span
                className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-gold"
                aria-hidden
              />
            )}
          </div>
        </div>
      </RevealItem>
    );
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-hidden p-0 sm:max-w-md">
        <SheetHeader className="border-b border-rule-strong/40 px-6 py-4 text-left">
          <p className="dept-label text-muted-foreground/70">
            Office of the Nightly Auditor
          </p>
          <SheetTitle className="font-display text-2xl">
            Auditor's Report
          </SheetTitle>
          <SheetDescription className="sr-only">
            A digest of the nightly auditor's findings — flags, drifts, budget
            notices, and proposed actions — grouped by kind.
          </SheetDescription>
        </SheetHeader>

        <div className="flex items-center justify-between px-6 py-2.5">
          <span className="font-mono text-[11px] text-muted-foreground">
            {sorted.length} finding{sorted.length === 1 ? "" : "s"}
            {unreadCount > 0 ? ` · ${unreadCount} unread` : ""}
          </span>
          {unreadCount > 0 && (
            <button
              onClick={() => markAllNotificationsRead()}
              className="inline-flex items-center gap-1 font-sans text-[10px] uppercase tracking-[0.14em] text-gold transition-colors hover:text-foreground"
            >
              <CheckCheck size={12} /> Mark all read
            </button>
          )}
        </div>

        <ScrollArea className="h-[calc(100vh-9.5rem)]">
          {sorted.length === 0 ? (
            <div className="px-6 py-10">
              <EmptyState
                seed={11}
                eyebrow="Audit · Clean"
                title="Nothing flagged"
                description="The nightly auditor sweeps your budgets, forecast, and merchants for anything worth a second look. When it finds something, it's filed here."
              />
            </div>
          ) : (
            <Reveal gap={0.04} delay={0.02} className="pb-8">
              {NOTICE_GROUPS.filter((g) => byGroup.has(g)).map((g) => (
                <div key={g}>
                  <SectionRule className="px-6 pb-1 pt-4">{g}</SectionRule>
                  {byGroup.get(g)!.map((n) => (
                    <Finding key={n.id} n={n} />
                  ))}
                </div>
              ))}
            </Reveal>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
};

export default AuditorsReport;
