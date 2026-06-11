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
      <PopoverTrigger className="relative grid h-9 w-9 place-items-center border-2 border-border bg-card text-foreground shadow-brutal-sm transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-brutal">
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 flex h-4 min-w-4 items-center justify-center border-2 border-border bg-destructive px-1 text-[10px] font-bold text-destructive-foreground">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="flex items-center justify-between border-b-2 border-border px-4 py-2">
          <span className="font-display text-sm font-bold uppercase">Notifications</span>
          {unreadCount > 0 && (
            <button
              onClick={() => markAllNotificationsRead()}
              className="text-xs font-bold uppercase text-primary hover:underline"
            >
              Mark all read
            </button>
          )}
        </div>
        <ScrollArea className="max-h-80">
          {notifications.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              You're all caught up.
            </p>
          ) : (
            <ul>
              {notifications.map((n) => (
                <li
                  key={n.id}
                  onClick={() => !n.read && markNotificationRead(n.id)}
                  className={`cursor-pointer border-b-2 border-border px-4 py-3 hover:bg-accent ${
                    n.read ? "opacity-60" : ""
                  }`}
                >
                  <div className="flex items-start gap-2">
                    {n.type === "budget_overrun" ? (
                      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-destructive" />
                    ) : n.type === "anomaly" ? (
                      <TrendingUp size={14} className="mt-0.5 shrink-0 text-orange-400" />
                    ) : !n.read ? (
                      <span className="mt-1.5 h-2 w-2 shrink-0 bg-primary" />
                    ) : null}
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-bold">{n.title}</span>
                      <p className="mt-0.5 text-xs text-muted-foreground">{n.message}</p>
                      {n.created_at && (
                        <p className="mt-1 text-[10px] text-muted-foreground/50">
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
