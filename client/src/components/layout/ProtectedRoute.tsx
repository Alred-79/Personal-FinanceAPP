import { useEffect, useRef, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useStore } from "@/store/store";

/**
 * Auth guard: checks the session cookie on first mount, then sends the user to
 * /login if they aren't signed in. While the check is still running it shows a
 * full screen loading state so child pages never flash before we know.
 */
export default function ProtectedRoute() {
  const location = useLocation();
  const [authChecking, setAuthChecking] = useState(true);
  const didCheck = useRef(false);

  const { isLoggedIn, userLoaded, fetchUser } = useStore();

  useEffect(() => {
    if (didCheck.current) return;
    didCheck.current = true;

    if (userLoaded) {
      setAuthChecking(false);
      return;
    }
    fetchUser().finally(() => setAuthChecking(false));
  }, [fetchUser, userLoaded]);

  if (authChecking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!isLoggedIn) {
    if (location.pathname === "/") return <Navigate to="/welcome" replace />;
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }

  return <Outlet />;
}
