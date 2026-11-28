import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { CURRENCIES, type Filters } from "../types";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/assistant", label: "AI Assistant" },
  { to: "/costs", label: "Cost Explorer" },
  { to: "/resources", label: "Resources" },
  { to: "/findings", label: "Findings" },
  { to: "/forecasts", label: "Forecasts" },
  { to: "/simulation", label: "Simulation Lab" },
  { to: "/anomalies", label: "Anomalies" },
  { to: "/imports", label: "Imports" },
  { to: "/audit", label: "Audit" },
];

export function Layout() {
  const { currency, setCurrency } = useCurrency();
  const [filters, setFilters] = useState<Filters | null>(null);

  useEffect(() => {
    api.filters().then(setFilters).catch(() => setFilters(null));
  }, []);

  const fresh = filters?.freshness;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-logo" src="/logo.svg" alt="CloudPilot AI" width={36} height={36} />
          <div>
            <div className="brand-name">CloudPilot AI</div>
            <div className="brand-tag">Predict. Simulate. Investigate. Act.</div>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="mini-note">Synthetic demo data</div>
          <div className="mini-note">No FX conversion — native currencies</div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">Cloud Operations Console</div>
          <div className="topbar-right">
            {fresh && (
              <span className={fresh.freshness_warning ? "pill warn" : "pill ok"}>
                {fresh.freshness_warning ? "Stale data" : "Fresh data"}
                {fresh.data_age_hours != null ? ` · ${fresh.data_age_hours}h` : ""}
              </span>
            )}
            <label className="currency-select">
              <span>Currency</span>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value as any)}
              >
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
