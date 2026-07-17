import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import AppShell from "./components/layout/AppShell.tsx";
import ProtectedRoute from "./components/layout/ProtectedRoute.tsx";
import ErrorBoundary from "./components/layout/ErrorBoundary.tsx";
import RouteFallback from "./components/layout/RouteFallback.tsx";
import { Toaster } from "@/components/ui/toaster";
import { GameModeProvider } from "@/store/gameMode";
import { ScanlineOverlay } from "@/components/custom/ScanlineOverlay/ScanlineOverlay";
import { apiBase } from "@/lib/apiBase";

// Route boundaries keep the public landing from downloading the protected app,
// charting, tax, and game surfaces before a visitor has chosen to enter.
const Landing = lazy(() => import("./pages/Landing/Landing.tsx"));
const Login = lazy(() => import("./pages/Login/Login.tsx"));
const Home = lazy(() => import("./pages/Home/Home.tsx"));
const Expedition = lazy(() => import("./pages/Expedition/Expedition.tsx"));
const Accounts = lazy(() => import("./pages/Accounts/Accounts.tsx"));
const Transactions = lazy(() => import("./pages/Transactions/Transactions.tsx"));
const Goals = lazy(() => import("./pages/Goals/Goals.tsx"));
const Budgets = lazy(() => import("./pages/Budgets/Budgets.tsx"));
const Subscriptions = lazy(() => import("./pages/Subscriptions/Subscriptions.tsx"));
const Almanac = lazy(() => import("./pages/Almanac/Almanac.tsx"));
const Income = lazy(() => import("./pages/Income/Income.tsx"));
const Forecast = lazy(() => import("./pages/Forecast/Forecast.tsx"));
const Reconcile = lazy(() => import("./pages/Reconcile/Reconcile.tsx"));
const Tax = lazy(() => import("./pages/Tax/Tax.tsx"));
const Settings = lazy(() => import("./pages/Settings/Settings.tsx"));
const Rules = lazy(() => import("./pages/Rules/Rules.tsx"));
const Keeper = lazy(() => import("./pages/Keeper/Keeper.tsx"));
const Debts = lazy(() => import("./pages/Debts/Debts.tsx"));
const Campaigns = lazy(() => import("./pages/Campaigns/Campaigns.tsx"));
const Outcomes = lazy(() => import("./pages/Outcomes/Outcomes.tsx"));

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
          <Suspense fallback={<RouteFallback />}>
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
              <Route path="/almanac" element={<Almanac />} />
              {/* The Income (freelancer wedge) route exists in every instance;
                  its NAV presence is gated by the server freelancer flag, and the
                  inner surface self-handles the disabled (404) state. */}
              <Route path="/income" element={<Income />} />
              <Route path="/rules" element={<Rules />} />
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
          </Suspense>
        </BrowserRouter>
      </GameModeProvider>
    </ErrorBoundary>
  </StrictMode>
);
