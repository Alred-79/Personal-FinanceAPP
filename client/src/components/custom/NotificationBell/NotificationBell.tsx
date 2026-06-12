import { FC, useEffect } from "react";
import { Bell, AlertTriangle, TrendingUp } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useStore } from "@/store/store";

/**
 * Notification bell.
 *
 * Shows how many nudges are unread, with a popover feed of budget overrun and
 * anomaly notifications. Polls the backend on mount and every 60s while mounted.
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

  useEffect(() => {
    if (!isLoggedIn) return;
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 60_000);
    return () => clearInterval(interval);
  }, [isLoggedIn, fetchNotifications]);

  if (!isLoggedIn) return null;

  return (
    <Popover>
      <PopoverTrigger className="press relative grid h-9 w-9 place-items-center border border-rule-strong/50 bg-card text-foreground shadow-plate transition-all hover:bg-wash">
        <Bell size={17} />
        {unreadCount > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full border border-background bg-debit px-1 font-mono text-[10px] font-semibold text-destructive-foreground">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="flex items-center justify-between border-b border-rule-strong/40 px-4 py-2.5">
          <span className="dept-label">Notices &amp; Nudges</span>
          {unreadCount > 0 && (
            <button
              onClick={() => markAllNotificationsRead()}
              className="font-sans text-[10px] uppercase tracking-[0.14em] text-gold hover:underline"
            >
              Mark all read
            </button>
          )}
        </div>
        <ScrollArea className="max-h-80">
          {notifications.length === 0 ? (
            <p className="px-4 py-8 text-center font-sans text-sm italic text-muted-foreground">
              You're all caught up.
            </p>
          ) : (
            <ul>
              {notifications.map((n) => (
                <li
                  key={n.id}
                  onClick={() => !n.read && markNotificationRead(n.id)}
                  className={`ledger-row cursor-pointer px-4 py-3 ${
                    n.read ? "opacity-55" : ""
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    {n.type === "budget_overrun" ? (
                      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-debit" />
                    ) : n.type === "anomaly" ? (
                      <TrendingUp size={14} className="mt-0.5 shrink-0 text-gold" />
                    ) : !n.read ? (
                      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-gold" />
                    ) : null}
                    <div className="min-w-0 flex-1">
                      <span className="font-sans text-sm font-semibold text-foreground">
                        {n.title}
                      </span>
                      <p className="mt-0.5 font-sans text-xs text-muted-foreground">
                        {n.message}
                      </p>
                      {n.created_at && (
                        <p className="mt-1 font-mono text-[10px] text-muted-foreground/50">
                          {new Date(n.created_at).toLocaleDateString(undefined, {
                            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                          })}
                        </p>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
};

export default NotificationBell;
