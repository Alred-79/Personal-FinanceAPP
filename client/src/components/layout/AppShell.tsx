import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { AssistantInterface } from "@/components/custom/AssistantInterface/AssistantInterface";
import { ChroniclerDrawer } from "@/components/custom/ChroniclerDrawer/ChroniclerDrawer";
import Header from "./Header";
import { titleForPath } from "./nav";

declare global {
  interface Window {
    Plaid: {
      create: (config: {
        token: string;
        onSuccess: (
          publicToken: string,
          metadata: { institution: { name: string } }
        ) => void;
        onExit: (err: Error | null) => void;
        onEvent: (eventName: string, metadata: unknown) => void;
      }) => { open: () => void };
    };
  }
}

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
  const [plaidHandler, setPlaidHandler] = useState<{ open: () => void } | null>(
    null
  );

  const {
    user,
    linkToken,
    logout,
    fetchLinkToken,
    exchangePublicToken,
  } = useStore();

  useEffect(() => {
    if (user && !linkToken) fetchLinkToken();
  }, [user, linkToken, fetchLinkToken]);

  useEffect(() => {
    if (!linkToken || !window.Plaid) return;
    const handler = window.Plaid.create({
      token: linkToken,
      onSuccess: async (publicToken, metadata) => {
        await exchangePublicToken(publicToken, metadata.institution.name);
        toast({
          title: "Account Connected",
          description: `Successfully connected ${metadata.institution.name}`,
        });
        navigate("/?new-account=true");
      },
      onExit: (err) => {
        if (err != null) console.error("Error during Link flow:", err);
      },
      onEvent: (eventName, metadata) => console.log("Event:", eventName, metadata),
    });
    setPlaidHandler(handler);
  }, [linkToken, navigate, toast, exchangePublicToken]);

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
