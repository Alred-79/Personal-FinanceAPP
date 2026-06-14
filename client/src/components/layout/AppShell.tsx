import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { usePlaidReady, type PlaidHandler } from "@/lib/plaid";
import { AssistantInterface } from "@/components/custom/AssistantInterface/AssistantInterface";
import { ChroniclerDrawer } from "@/components/custom/ChroniclerDrawer/ChroniclerDrawer";
import Header from "./Header";
import { titleForPath } from "./nav";

/**
 * Layout for signed in users: a fixed left sidebar on desktop (a drawer on
 * mobile), a top header, and the routed page in a centered content area with a
 * max width. The parent ProtectedRoute handles auth, so this component assumes
 * the user is already signed in.
 */
export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const [plaidHandler, setPlaidHandler] = useState<PlaidHandler | null>(null);
  const plaidReady = usePlaidReady();

  const {
    user,
    linkToken,
    logout,
    fetchLinkToken,
    exchangePublicToken,
    fetchUserSettings,
    settingsLoaded,
  } = useStore();

  // Load instance settings once so app-wide flags (e.g. the tax-feature nav
  // gate) are populated before the nav renders.
  useEffect(() => {
    if (user && !settingsLoaded) fetchUserSettings();
  }, [user, settingsLoaded, fetchUserSettings]);

  // Keep the latest exchange handler in a ref so the create() effect depends
  // only on the token + script readiness — not on closures that change each
  // render (which would re-create and leak Link handlers).
  const onSuccessRef = useRef<
    (publicToken: string, name: string) => Promise<void>
  >(async () => {});
  onSuccessRef.current = async (publicToken, name) => {
    try {
      await exchangePublicToken(publicToken, name);
      toast({
        title: "Account Connected",
        description: `Successfully connected ${name}`,
      });
      navigate("/?new-account=true");
    } catch {
      toast({
        variant: "destructive",
        title: "Could not connect your bank",
        description: "The connection couldn't be completed. Please try again.",
      });
    }
  };

  useEffect(() => {
    if (user && !linkToken) fetchLinkToken();
  }, [user, linkToken, fetchLinkToken]);

  useEffect(() => {
    if (!linkToken || !plaidReady || !window.Plaid) return;
    const handler = window.Plaid.create({
      token: linkToken,
      onSuccess: (publicToken, metadata) =>
        onSuccessRef.current(publicToken, metadata.institution.name),
      onExit: (err) => {
        if (err != null) console.error("Error during Link flow:", err);
      },
      onEvent: (eventName, metadata) => console.log("Event:", eventName, metadata),
    });
    setPlaidHandler(handler);
    // Destroy the handler on cleanup so re-creating it (new token, unmount)
    // doesn't leak the prior Link iframe/listeners.
    return () => {
      handler.destroy?.();
      setPlaidHandler(null);
    };
  }, [linkToken, plaidReady]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };
  const handleConnectBank = () => plaidHandler?.open();

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header
        title={titleForPath(location.pathname)}
        onConnectBank={handleConnectBank}
        canConnectBank={!!plaidHandler}
        onLogout={handleLogout}
      />
      <main className="flex-1 px-4 py-8 md:px-8 md:py-10">
        <div className="mx-auto w-full max-w-[1400px]">
          <Outlet />
        </div>
      </main>

      <AssistantInterface />
      {/* The Chronicler drawer: `/`-summoned over any page, every mode. */}
      <ChroniclerDrawer />
    </div>
  );
}
