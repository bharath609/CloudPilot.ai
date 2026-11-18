import { HashRouter, Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { AdvisorPage } from "./pages/AdvisorPage";
import { AuditPage } from "./pages/AuditPage";
import { CostsPage } from "./pages/CostsPage";
import { FindingsPage } from "./pages/FindingsPage";
import { ForecastsPage } from "./pages/ForecastsPage";
import { ImportsPage } from "./pages/ImportsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ResourcesPage } from "./pages/ResourcesPage";
import { AppStateProvider } from "./state/AppState";

export default function App() {
  return (
    <HashRouter>
      <AppStateProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/costs" element={<CostsPage />} />
            <Route path="/resources" element={<ResourcesPage />} />
            <Route path="/findings" element={<FindingsPage />} />
            <Route path="/advisor" element={<AdvisorPage />} />
            <Route path="/forecasts" element={<ForecastsPage />} />
            <Route path="/imports" element={<ImportsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout>
      </AppStateProvider>
    </HashRouter>
  );
}
