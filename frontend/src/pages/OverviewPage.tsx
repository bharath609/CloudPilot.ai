import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { formatDate, formatMoney, pct } from "../lib";
import { Badge, Card, ErrorBox, Loading, Stat } from "../components/Card";
import type { Filters, ImportRow, Summary } from "../types";

export function OverviewPage() {
  const { currency } = useCurrency();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [filters, setFilters] = useState<Filters | null>(null);
  const [imports, setImports] = useState<ImportRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([api.summary(currency), api.filters(), api.imports()])
      .then(([s, f, i]) => {
        if (!alive) return;
        setSummary(s);
        setFilters(f);
        setImports(i.imports);
        setError(null);
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [currency]);

  const fresh = filters?.freshness;

  return (
    <div className="stack">
      <Card
        title="Command Center"
        subtitle="Spend, savings and data freshness at a glance"
        right={<Badge tone="info">{currency} view</Badge>}
      >
        {error && <ErrorBox message={error} />}
        {!summary && !error && <Loading what="summary" />}
        {summary && (
          <>
            <div className="stats-grid">
              <Stat label="TOTAL SPEND" value={formatMoney(summary.total_spend, currency)} hint={`${summary.window.days} days`} />
              <Stat label="BILLING ROWS" value={summary.row_count.toLocaleString()} hint="De-duplicated" />
              <Stat label="RECENT 30D VS PRIOR 30D" value={pct(summary.recent_vs_prior_pct)} hint="Exact decimal change" />
              <Stat
                label="DATA FRESHNESS"
                value={fresh?.freshness_warning ? "Stale" : "Fresh"}
                hint={fresh?.data_age_hours != null ? `${fresh.data_age_hours}h old` : "No imports"}
              />
            </div>

            <div className="two-col">
              <div>
                <h3 className="section-title">Top services</h3>
                <div className="bars">
                  {summary.top_services.map((s) => (
                    <div className="bar-row" key={s.service}>
                      <div className="bar-label">
                        <span>{s.service}</span>
                        <span className="muted">{formatMoney(s.amount, currency)} · {s.pct}%</span>
                      </div>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${Math.min(100, s.pct)}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="facts">
                <h3 className="section-title">Data & imports</h3>
                <div className="fact"><span>Billing window</span><b>{formatDate(summary.window.start)} → {formatDate(summary.window.end)}</b></div>
                <div className="fact"><span>Last import</span><b>{formatDate(filters?.last_import_at)}</b></div>
                <div className="fact"><span>Imports</span><b>{imports.length}</b></div>
                <div className="fact"><span>Data quality</span><b>{fresh?.data_quality ?? "—"}</b></div>
                <div className="fact"><span>Currencies</span><b>{filters?.currencies.join(" · ")}</b></div>
                {fresh?.freshness_warning && (
                  <div className="inline-warn">⚠ {fresh.note}</div>
                )}
                <div className="inline-note">{filters?.note}</div>
              </div>
            </div>
          </>
        )}
      </Card>

      <Card title="Start here" subtitle="Common next steps">
        <div className="quick-links">
          <Link className="quick-link" to="/findings">Review findings →</Link>
          <Link className="quick-link" to="/simulation">Run a what-if →</Link>
          <Link className="quick-link" to="/anomalies">Check anomalies →</Link>
          <Link className="quick-link" to="/forecasts">View forecasts →</Link>
        </div>
      </Card>
    </div>
  );
}
