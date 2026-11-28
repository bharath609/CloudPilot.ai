import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/OverviewPage";
import { CostExplorerPage } from "./pages/CostExplorerPage";
import { ResourcesPage } from "./pages/ResourcesPage";
import { FindingsPage } from "./pages/FindingsPage";
import { ForecastsPage } from "./pages/ForecastsPage";
import { SimulationLabPage } from "./pages/SimulationLabPage";
import { AnomaliesPage } from "./pages/AnomaliesPage";
import { ImportsPage } from "./pages/ImportsPage";
import { AuditPage } from "./pages/AuditPage";
import { AssistantPage } from "./pages/AssistantPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="costs" element={<CostExplorerPage />} />
        <Route path="resources" element={<ResourcesPage />} />
        <Route path="findings" element={<FindingsPage />} />
        <Route path="forecasts" element={<ForecastsPage />} />
        <Route path="simulation" element={<SimulationLabPage />} />
        <Route path="anomalies" element={<AnomaliesPage />} />
        <Route path="imports" element={<ImportsPage />} />
        <Route path="audit" element={<AuditPage />} />
      </Route>
    </Routes>
  );
}
