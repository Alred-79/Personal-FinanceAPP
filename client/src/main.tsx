import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import Home from "./pages/Home/Home.tsx";
import Expedition from "./pages/Expedition/Expedition.tsx";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Accounts from "./pages/Accounts/Accounts.tsx";
import Transactions from "./pages/Transactions/Transactions.tsx";
import Goals from "./pages/Goals/Goals.tsx";
import Budgets from "./pages/Budgets/Budgets.tsx";
import Subscriptions from "./pages/Subscriptions/Subscriptions.tsx";
import Forecast from "./pages/Forecast/Forecast.tsx";
import Reconcile from "./pages/Reconcile/Reconcile.tsx";
import Tax from "./pages/Tax/Tax.tsx";
import Login from "./pages/Login/Login.tsx";
import Landing from "./pages/Landing/Landing.tsx";
import Settings from "./pages/Settings/Settings.tsx";
import Keeper from "./pages/Keeper/Keeper.tsx";
import Debts from "./pages/Debts/Debts.tsx";
import Campaigns from "./pages/Campaigns/Campaigns.tsx";
import Outcomes from "./pages/Outcomes/Outcomes.tsx";
import AppShell from "./components/layout/AppShell.tsx";
import ProtectedRoute from "./components/layout/ProtectedRoute.tsx";
import ErrorBoundary from "./components/layout/ErrorBoundary.tsx";
import { Toaster } from "@/components/ui/toaster";
import { GameModeProvider } from "@/store/gameMode";
import { ScanlineOverlay } from "@/components/custom/ScanlineOverlay/ScanlineOverlay";
import { apiBase } from "@/lib/apiBase";

// Wipe the assistant's history when the user closes the tab. `sendBeacon` is
// the only request guaranteed to fire during unload — a regular `fetch` is
// often cancelled before it leaves the page.
window.addEventListener("beforeunload", () => {
  navigator.sendBeacon(`${apiBase}/assistant/clear/`);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <GameModeProvider>
        <BrowserRouter>
          <Toaster />
          <ScanlineOverlay />
          <Routes>
          {/* Public, no login needed: the marketing landing sits before /login. */}
          <Route path="/welcome" element={<Landing />} />
          {/* Stands alone, no login needed */}
          <Route path="/login" element={<Login />} />

          {/* The auth guard wraps every page that needs a login */}
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              {/* Two-homes IA (v4 §10.1): full mode → Expedition, off/ambient →
                  Overview. Home reads ONLY the mode variable. */}
              <Route path="/" element={<Home />} />
              {/* The Expedition map exists in every mode (fork-smell law). */}
              <Route path="/expedition" element={<Expedition />} />
              <Route path="/accounts" element={<Accounts />} />
              <Route path="/transactions" element={<Transactions />} />
              <Route path="/goals" element={<Goals />} />
              <Route path="/budgets" element={<Budgets />} />
              <Route path="/subscriptions" element={<Subscriptions />} />
              <Route path="/forecast" element={<Forecast />} />
              <Route path="/reconcile" element={<Reconcile />} />
              {/* The Tax Organizer route exists in every instance; the page
                  self-handles the disabled state, and its NAV presence is gated
                  by the server tax-feature flag (taxOnly). */}
              <Route path="/tax" element={<Tax />} />
              <Route path="/settings" element={<Settings />} />
              {/* The Keeper route renders in every mode (off redirects to
                  Settings) so the no-mode-only-pages rule holds; its presence in
                  NAV is the flag, not the route's existence. */}
              <Route path="/keeper" element={<Keeper />} />
              {/* Debts/bosses: route exists in every mode (off redirects to
                  Settings); its NAV presence is the gameOnly flag. */}
              <Route path="/debts" element={<Debts />} />
              {/* The Campaign (pkg 10): route exists in every mode (off
                  redirects to Settings); NAV presence is the gameOnly flag.
                  The surface renders no countdown — scan-enforced. */}
              <Route path="/campaigns" element={<Campaigns />} />
              {/* Outcomes v0 is INTERNAL: a plain cohort-comparison page,
                  identical in every mode, never in nav. */}
              <Route path="/outcomes" element={<Outcomes />} />
            </Route>
          </Route>
          </Routes>
        </BrowserRouter>
      </GameModeProvider>
    </ErrorBoundary>
  </StrictMode>
);
