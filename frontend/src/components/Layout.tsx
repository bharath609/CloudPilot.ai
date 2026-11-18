import { NavLink, useLocation } from "react-router-dom";

import { exportUrl } from "../api/client";
import { useAppState } from "../state/AppState";
import { Badge, Icon } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: "overview", end: true },
  { to: "/costs", label: "Cost Explorer", icon: "costs" },
  { to: "/resources", label: "Resource Health", icon: "resources" },
  { to: "/findings", label: "Findings", icon: "findings" },
  { to: "/advisor", label: "AI Advisor", icon: "advisor" },
  { to: "/forecasts", label: "Forecasts", icon: "forecasts" },
  { to: "/imports", label: "Imports", icon: "imports" },
  { to: "/audit", label: "Audit", icon: "audit" },
];

const TITLES: Record<string, { title: string; subtitle: string }> = {
  "/": {
    title: "Overview",
    subtitle: "Spend, savings and data freshness at a glance.",
  },
  "/costs": {
    title: "Cost Explorer",
    subtitle: "Filter and chart exact, currency-partitioned spend.",
  },
  "/resources": {
    title: "Resource Health",
    subtitle: "Utilization, observation basis and ownership. Read-only.",
  },
  "/findings": {
    title: "Optimization Findings",
    subtitle: "Deterministic candidates for human review. Nothing is applied.",
  },
  "/advisor": {
    title: "AI Advisor",
    subtitle: "Optional explanation of computed findings. Disabled by default.",
  },
  "/forecasts": {
    title: "Forecasts",
    subtitle: "Transparent baseline projection with a held-out error estimate.",
  },
  "/imports": {
    title: "Imports",
    subtitle: "Upload CSV exports and inspect validation lineage.",
  },
  "/audit": {
    title: "Audit",
    subtitle: "Append-only decisions and advisor report history.",
  },
};

export function Layout({ children }: { children: React.ReactNode }) {
  const { filters, filtersError, currency, setCurrency, health, healthError } = useAppState();
  const location = useLocation();
  const meta = TITLES[location.pathname] ?? TITLES["/"];
  const live = health?.status === "ok" && !healthError;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="28" height="28" role="presentation">
              <path
                d="M6 19.5 16 5l10 14.5-10 7z"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinejoin="round"
              />
              <path d="M16 12v9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </span>
          <span className="brand-text">
            <strong>CloudPilot AI</strong>
            <small>Local FinOps console</small>
          </span>
        </div>

        <nav className="nav" aria-label="Main navigation">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          {filters?.contains_sample_data ? (
            <Badge tone="warn">Synthetic sample data</Badge>
          ) : (
            <Badge tone="neutral">No sample import detected</Badge>
          )}
          <p>
            CloudPilot never reads from or writes to a cloud account. Uploads are parsed
            locally and money is stored as exact decimals.
          </p>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="page-heading">
            <h1>{meta.title}</h1>
            <p>{meta.subtitle}</p>
          </div>

          <div className="topbar-tools">
            <span className={`health ${live ? "health-ok" : "health-bad"}`}>
              <span className="dot" aria-hidden="true" />
              {live ? "API connected" : filtersError ? "API unreachable" : "Checking API"}
            </span>

            {filters && filters.currencies.length > 0 && (
              <label className="currency">
                <span className="sr-only">Display currency</span>
                <select
                  value={currency}
                  onChange={(event) => setCurrency(event.target.value)}
                  aria-label="Display currency"
                >
                  {filters.currencies.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className="exports">
              <a className="btn btn-ghost" href={exportUrl("/exports/findings.csv")} download>
                Export CSV
              </a>
              <a className="btn btn-ghost" href={exportUrl("/exports/summary.md")} download>
                Export report
              </a>
            </div>
          </div>
        </header>

        {filters?.contains_sample_data && (
          <div className="sample-banner" role="note">
            <strong>Synthetic demo data is loaded.</strong>
            <span>
              Every figure below is illustrative sample data, not a vendor quote. Replace it by
              importing your own billing and utilization CSV files.
            </span>
          </div>
        )}

        <main className="content">{children}</main>

        <footer className="foot">
          <span>
            Local-first · no cloud credentials required · findings require human review
          </span>
          <span>
            {filters
              ? `${filters.import_count} import(s) · last import ${
                  filters.last_import_filename ?? "—"
                }`
              : "Loading data lineage"}
          </span>
        </footer>
      </div>
    </div>
  );
}
