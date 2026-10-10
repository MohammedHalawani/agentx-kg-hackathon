import { Component, lazy, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppShell } from "@/components/app-shell";
import { OperationsProvider } from "@/state/operations";
import { PreferencesProvider, usePreferences } from "@/state/preferences";
import { OperationsPage } from "@/pages/operations";
import { Button } from "@/components/ui/button";
import { CanopusProvider } from "@/state/canopus";
import { useMediaQuery } from "@/hooks/use-media-query";
import { BASE_PATH, LAB, asset } from "@/config";
const InvestigationPage = lazy(() =>
  import("@/pages/investigation").then((m) => ({
    default: m.InvestigationPage,
  })),
);
const DecisionsPage = lazy(() =>
  import("@/pages/decisions").then((m) => ({ default: m.DecisionsPage })),
);
const ExplorePage = lazy(() =>
  import("@/pages/explore").then((m) => ({ default: m.ExplorePage })),
);
const AuditPage = lazy(() =>
  import("@/pages/audit").then((m) => ({ default: m.AuditPage })),
);
const SettingsPage = lazy(() =>
  import("@/pages/settings").then((m) => ({ default: m.SettingsPage })),
);
class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error) {
    console.error("Suhail UI failed to render:", error.message);
  }
  render() {
    if (this.state.failed)
      return (
        <div className="app-error">
          <img src={asset("suhail.svg")} width="44" alt="Suhail" />
          <h1>The workspace could not load.</h1>
          <p>
            {LAB
              ? "Reload to restore your locally saved cases."
              : "Reload to read the workspace from the Suhail backend again."}
          </p>
          <Button onClick={() => window.location.reload()}>
            Reload workspace
          </Button>
        </div>
      );
    return this.props.children;
  }
}
function AppRoutes() {
  const { preferences } = usePreferences();
  const mobile = useMediaQuery("(max-width: 600px)");
  return (
    <>
      <BrowserRouter basename={BASE_PATH}>
        <CanopusProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<Navigate to="/operations" replace />} />
              <Route path="/operations" element={<OperationsPage />} />
              <Route path="/cases/:caseId" element={<InvestigationPage />} />
              <Route
                path="/investigation"
                element={
                  <Navigate
                    to={LAB ? "/cases/SHP-10482" : "/operations"}
                    replace
                  />
                }
              />
              <Route path="/decisions" element={<DecisionsPage />} />
              <Route path="/explore" element={<ExplorePage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/operations" replace />} />
            </Route>
          </Routes>
        </CanopusProvider>
      </BrowserRouter>
      <Toaster
        theme={preferences.theme}
        position={
          mobile
            ? "top-center"
            : preferences.language === "ar"
              ? "bottom-right"
              : "bottom-left"
        }
        richColors
        closeButton
        offset={{ bottom: "24px", left: "24px", right: "24px" }}
        mobileOffset={{ top: "12px", left: "12px", right: "12px" }}
      />
    </>
  );
}
export default function App() {
  return (
    <ErrorBoundary>
      <PreferencesProvider>
        <TooltipProvider>
          <OperationsProvider>
            <AppRoutes />
          </OperationsProvider>
        </TooltipProvider>
      </PreferencesProvider>
    </ErrorBoundary>
  );
}
