import { FC, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bell,
  AlertTriangle,
  TrendingUp,
  FileText,
  CheckCheck,
  type LucideIcon,
} from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { Guilloche } from "@/components/engraving/Guilloche";
import { useStore } from "@/store/store";
import type { Notification } from "@/types";

/**
 * The notice registry. Each kind carries its engraved tell (icon + ink) and the
 * ledger page it deep-links to. `tone` stays inside the colour law: debit-red
 * for money-out warnings, gold for an attention nudge, neutral otherwise — never
 * the amber `--game-accent`, which belongs to the game layer alone.
 */
const NOTICE: Record<
  string,
  { icon: LucideIcon; tone: "debit" | "gold" | "muted"; to?: string; verb?: string }
> = {
  budget_overrun: { icon: AlertTriangle, tone: "debit", to: "/budgets", verb: "Review budget" },
  anomaly: { icon: TrendingUp, tone: "gold", to: "/transactions", verb: "Inspect ledger" },
};
const FALLBACK = { icon: FileText, tone: "muted" as const, to: undefined, verb: undefined };

const TONE_TEXT = { debit: "text-debit", gold: "text-gold", muted: "text-muted-foreground" };
const TONE_EDGE = {
  debit: "border-l-debit/70",
  gold: "border-l-gold/70",
  muted: "border-l-transparent",
};

/** Compact "2h ago" / "3d ago" / "Jun 14" stamp from an ISO string. */
function relTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = (Date.now() - then) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86_400) return `${Math.round(s / 3600)}h ago`;
  if (s < 604_800) return `${Math.round(s / 86_400)}d ago`;
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * The Notices & Nudges centre.
 *
 * A bell + unread badge opens a grouped feed: unread notices first, then the
 * read "earlier" pile, each typed (budget overrun, anomaly, …) with its own ink
 * and a deep-link to the relevant ledger page. Activating a notice marks it read
 * and, when it carries a destination, navigates there. Polls on mount and every
 * 60s while mounted.
 */
const NotificationBell: FC = () => {
  const {
    isLoggedIn,
    notifications,
    unreadCount,
    fetchNotifications,
    markNotificationRead,
    markAllNotificationsRead,
  } = useStore();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!isLoggedIn) return;
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 60_000);
    return () => clearInterval(interval);
  }, [isLoggedIn, fetchNotifications]);

  if (!isLoggedIn) return null;

  const sorted = [...notifications].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? "")
  );
  const unread = sorted.filter((n) => !n.read);
  const earlier = sorted.filter((n) => n.read);

  const activate = (n: Notification) => {
    if (!n.read) markNotificationRead(n.id);
    const to = (NOTICE[n.type] ?? FALLBACK).to;
    if (to) {
      setOpen(false);
      navigate(to);
    }
  };

  const Row = ({ n }: { n: Notification }) => {
    const meta = NOTICE[n.type] ?? FALLBACK;
    const Icon = meta.icon;
    return (
      <RevealItem>
        <button
          type="button"
          onClick={() => activate(n)}
          className={`ledger-row group block w-full border-l-2 px-4 py-3 text-left transition-colors ${
            TONE_EDGE[meta.tone]
          } ${n.read ? "opacity-60" : ""}`}
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
              <p className="mt-0.5 font-sans text-xs text-muted-foreground">{n.message}</p>
              {meta.verb && (
                <span className="mt-1 inline-block font-sans text-[10px] uppercase tracking-[0.14em] text-gold opacity-0 transition-opacity group-hover:opacity-100">
                  {meta.verb} →
                </span>
              )}
            </div>
            {!n.read && (
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" aria-hidden />
            )}
          </div>
        </button>
      </RevealItem>
    );
  };

  const GroupLabel = ({ children }: { children: string }) => (
    <p className="dept-label px-4 pb-1 pt-3 text-muted-foreground/70">{children}</p>
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={`Notices${unreadCount > 0 ? `, ${unreadCount} unread` : ""}`}
        className="press relative grid h-9 w-9 place-items-center border border-rule-strong/50 bg-card text-foreground shadow-plate transition-all hover:bg-wash"
      >
        <Bell size={17} />
        {unreadCount > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full border border-background bg-debit px-1 font-mono text-[10px] font-semibold text-destructive-foreground">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-96 p-0" align="end">
        <div className="flex items-center justify-between border-b border-rule-strong/40 px-4 py-2.5">
          <span className="dept-label">Notices &amp; Nudges</span>
          {unreadCount > 0 && (
            <button
              onClick={() => markAllNotificationsRead()}
              className="inline-flex items-center gap-1 font-sans text-[10px] uppercase tracking-[0.14em] text-gold transition-colors hover:text-foreground"
            >
              <CheckCheck size={12} /> Mark all read
            </button>
          )}
        </div>
        <ScrollArea className="max-h-[26rem]">
          {sorted.length === 0 ? (
            <EmptyNotices />
          ) : (
            <Reveal gap={0.045} delay={0.02} className="pb-2">
              {unread.length > 0 && <GroupLabel>Unread</GroupLabel>}
              {unread.map((n) => (
                <Row key={n.id} n={n} />
              ))}
              {earlier.length > 0 && (
                <GroupLabel>{unread.length > 0 ? "Earlier" : "All read"}</GroupLabel>
              )}
              {earlier.map((n) => (
                <Row key={n.id} n={n} />
              ))}
            </Reveal>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
};

/** Compact, popover-scale "all caught up" plate (the full-page EmptyState
 * showpiece is too large for this surface). */
function EmptyNotices() {
  return (
    <div className="relative flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div aria-hidden className="relative grid h-16 w-16 place-items-center">
        <div className="absolute inset-0 text-gold/25">
          <Guilloche size={64} rings={4} seed={5} strokeWidth={0.5} />
        </div>
        <Bell size={20} className="text-muted-foreground" />
      </div>
      <p className="font-display text-base text-foreground">You're all caught up.</p>
      <p className="max-w-[15rem] font-sans text-xs text-muted-foreground">
        Budget overruns and unusual charges will surface here.
      </p>
    </div>
  );
}

export default NotificationBell;
