/**
 * THROWAWAY dev harness for comparing the three nav treatments (tabs+Tools,
 * sidebar rail, ⌘K palette) without logging in. Renders the REAL Header +
 * SidebarRail against a tiny seeded store. Flip styles with the header's
 * NavVariantSwitch; flip theme with ◐. Remove with the other dev routes.
 */
import { useEffect, useState } from "react";
import { useStore } from "@/store/store";
import { useNavVariant } from "@/lib/navVariant";
import Header from "@/components/layout/Header";
import SidebarRail from "@/components/layout/SidebarRail";

export default function DevNav() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    useStore.setState({
      user: { id: 1, username: "advik", full_name: "Advik" } as never,
      isLoggedIn: true,
      taxFeaturesEnabled: true,
    });
  }, []);

  const navVariant = useNavVariant();

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <button
        onClick={() => setDark((d) => !d)}
        className="fixed bottom-4 right-4 z-[9999] grid h-10 w-10 place-items-center border border-rule-strong/50 bg-card text-foreground shadow-plate"
      >
        ◐
      </button>

      <Header
        title="Overview"
        onConnectBank={() => {}}
        canConnectBank={false}
        onLogout={() => {}}
      />

      <div className="flex flex-1">
        {navVariant === "sidebar" && <SidebarRail />}
        <main className="min-w-0 flex-1 px-4 py-8 md:px-8">
          <div className="mx-auto w-full max-w-[1400px]">
            <div className="grid h-64 place-items-center border border-dashed border-rule-strong/40 bg-card/40 text-center">
              <div>
                <p className="font-display text-2xl text-foreground">Nav preview</p>
                <p className="mt-1 font-sans text-sm text-muted-foreground">
                  Current style: <span className="text-gold">{navVariant}</span> — flip it
                  with the switch in the header (top-right).
                </p>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
