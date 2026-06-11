import { useEffect, useRef, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { useStore } from "@/store/store";

/**
 * Auth guard: checks the session cookie on first mount, then sends the user to
 * /login if they aren't signed in. While the check is still running it shows a
 * full screen loading state so child pages never flash before we know.
 */
export default function ProtectedRoute() {
  const navigate = useNavigate();
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

  useEffect(() => {
    if (authChecking) return;
    if (!isLoggedIn) {
      navigate("/login", { replace: true });
    }
  }, [authChecking, isLoggedIn, navigate]);

  if (authChecking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!isLoggedIn) return null;

  return <Outlet />;
}
