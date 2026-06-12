import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import Overview from "./pages/Overview/Overview.tsx";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Accounts from "./pages/Accounts/Accounts.tsx";
import Transactions from "./pages/Transactions/Transactions.tsx";
import Goals from "./pages/Goals/Goals.tsx";
import Budgets from "./pages/Budgets/Budgets.tsx";
import Subscriptions from "./pages/Subscriptions/Subscriptions.tsx";
import Forecast from "./pages/Forecast/Forecast.tsx";
import Login from "./pages/Login/Login.tsx";
import Settings from "./pages/Settings/Settings.tsx";
import Keeper from "./pages/Keeper/Keeper.tsx";
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
          {/* Stands alone, no login needed */}
          <Route path="/login" element={<Login />} />

          {/* The auth guard wraps every page that needs a login */}
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route path="/" element={<Overview />} />
              <Route path="/accounts" element={<Accounts />} />
              <Route path="/transactions" element={<Transactions />} />
              <Route path="/goals" element={<Goals />} />
              <Route path="/budgets" element={<Budgets />} />
              <Route path="/subscriptions" element={<Subscriptions />} />
              <Route path="/forecast" element={<Forecast />} />
              <Route path="/settings" element={<Settings />} />
              {/* The Keeper route renders in every mode (off redirects to
                  Settings) so the no-mode-only-pages rule holds; its presence in
                  NAV is the flag, not the route's existence. */}
              <Route path="/keeper" element={<Keeper />} />
            </Route>
          </Route>
          </Routes>
        </BrowserRouter>
      </GameModeProvider>
    </ErrorBoundary>
  </StrictMode>
);
