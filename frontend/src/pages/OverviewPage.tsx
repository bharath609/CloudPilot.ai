import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import { useQuery } from "../api/hooks";
import type { Finding, TrendPoint } from "../api/types";
import { CHART, MoneyTooltip, axisProps } from "../components/charts";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Notes,
  Stat,
  riskTone,
} from "../components/ui";
import {
  compactMoney,
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatRatioPercent,
  percentChange,
  plotValue,
  relativeTime,
  sumDecimals,
  titleCase,
} from "../lib/money";
import { useAppState } from "../state/AppState";

function recentComparison(points: TrendPoint[], currency: string): string | null {
  const daily = points
    .filter((point) => !currency || point.currency === currency)
    .slice()
    .sort((a, b) => a.bucket.localeCompare(b.bucket));
  if (daily.length < 60) return null;
  const previous = daily.slice(-60, -30);
  const recent = daily.slice(-30);
  if (previous.length < 30 || recent.length < 30) return null;
  return percentChange(
    sumDecimals(previous.map((point) => point.amount)),
    sumDecimals(recent.map((point) => point.amount)),
  );
}

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <li className="list-row">
      <div>
        <span className="mono">{finding.resource_id}</span>
        <span className="muted">
          {titleCase(finding.finding_type)} · {finding.environment} · {finding.project}
        </span>
      </div>
      <div className="list-row-end">
        <strong>{formatMoney(finding.estimated_monthly_savings, finding.currency)}</strong>
        <Badge tone={riskTone(finding.risk)}>{titleCase(finding.risk)} risk</Badge>
      </div>
    </li>
  );
}

export function OverviewPage() {
  const { currency, filters } = useAppState();
  const summary = useQuery((signal) => api.summary({ currency }, signal), [currency]);
  const services = useQuery(
    (signal) => api.breakdown({ dimension: "service", currency, limit: 6 }, signal),
    [currency],
  );
  const trends = useQuery(
    (signal) => api.trends({ granularity: "day", currency }, signal),
    [currency],
  );
  const findings = useQuery(
    (signal) => api.findings({ currency, limit: 4 }, signal),
    [currency],
  );
  const forecast = useQuery((signal) => api.latestForecast(signal), []);

  const code = currency || summary.data?.totals[0]?.currency || "";
  const total = summary.data?.totals.find((item) => item.currency === code);
  const comparison = trends.data ? recentComparison(trends.data.points, code) : null;
  const series =
    forecast.data?.series.find((item) => item.currency === code) ?? forecast.data?.series[0];
  const openSavings = findings.data
    ? sumDecimals(findings.data.items.map((item) => item.estimated_monthly_savings))
    : null;

  const chartData = (trends.data?.points ?? [])
    .filter((point) => !code || point.currency === code)
    .map((point) => ({
      label: point.bucket,
      exact: point.amount,
      currency: point.currency,
      value: plotValue(point.amount),
      detail: `${point.row_count} billing row(s)`,
    }));

  return (
    <div className="stack">
      <section className="stat-grid">
        {summary.loading && <Loading rows={1} />}
        {summary.error && <ErrorNote message={summary.error} onRetry={summary.refetch} />}
        {summary.data && (
          <>
            <Stat
              label="Total spend"
              value={formatMoney(total?.amount ?? "0", code)}
              hint={
                summary.data.window.start
                  ? `${formatDate(summary.data.window.start)} – ${formatDate(
                      summary.data.window.end,
                    )} · ${summary.data.window.days} days`
                  : "No billing window"
              }
              tone="accent"
            />
            <Stat
              label="Recent 30 days vs prior 30"
              value={comparison ?? "Not enough history"}
              hint="Exact decimal change; grouped from daily stored spend."
              tone={
                comparison?.startsWith("+") ? "danger" : comparison ? "ok" : "neutral"
              }
            />
            <Stat
              label="Billing rows counted"
              value={summary.data.row_count.toLocaleString("en")}
              hint={`${summary.data.excluded_duplicate_rows} duplicate row(s) excluded`}
            />
            <Stat
              label="Savings in latest findings"
              value={formatMoney(openSavings ?? "0", code)}
              hint={`${findings.data?.items.length ?? 0} finding(s) previewed`}
              tone="warn"
            />
          </>
        )}
      </section>

      <div className="grid grid-2">
        <Card
          title="Daily spend"
          subtitle="Exact values in the tooltip; the plotted line is an approximate scale."
        >
          {trends.loading && <Loading />}
          {trends.error && <ErrorNote message={trends.error} onRetry={trends.refetch} />}
          {trends.data &&
            (chartData.length === 0 ? (
              <Empty title="No spend in this scope">
                Import a billing CSV or clear the currency filter.
              </Empty>
            ) : (
              <div className="chart-box">
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="overview-spend" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={CHART.accent} stopOpacity={0.45} />
                        <stop offset="100%" stopColor={CHART.accent} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={CHART.grid} strokeDasharray="3 4" vertical={false} />
                    <XAxis
                      dataKey="label"
                      {...axisProps}
                      minTickGap={28}
                      tickFormatter={(value: string) => value.slice(5)}
                    />
                    <YAxis
                      {...axisProps}
                      width={64}
                      tickFormatter={(value: number) => compactMoney(String(value), code)}
                    />
                    <Tooltip content={<MoneyTooltip currency={code} />} />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke={CHART.accent}
                      strokeWidth={2}
                      fill="url(#overview-spend)"
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ))}
        </Card>

        <Card title="Top services" subtitle="Largest first, current selection only.">
          {services.loading && <Loading />}
          {services.error && <ErrorNote message={services.error} onRetry={services.refetch} />}
          {services.data &&
            (services.data.items.length === 0 ? (
              <Empty title="No service spend yet" />
            ) : (
              <ul className="bar-list">
                {services.data.items.map((item) => (
                  <li key={item.key}>
                    <div className="bar-list-head">
                      <span>{item.key}</span>
                      <strong>{formatMoney(item.amount, item.currency)}</strong>
                    </div>
                    <div className="bar-track" aria-hidden="true">
                      <span style={{ width: `${Math.min(Number(item.share_pct), 100)}%` }} />
                    </div>
                    <span className="muted">
                      {formatPercent(item.share_pct)} of spend · {item.row_count} row(s)
                    </span>
                  </li>
                ))}
              </ul>
            ))}
        </Card>
      </div>

      <div className="grid grid-2">
        <Card
          title="Latest findings"
          subtitle="Deterministic candidates. Nothing is applied automatically."
          actions={
            <Link className="btn btn-small" to="/findings">
              Open findings
            </Link>
          }
        >
          {findings.loading && <Loading />}
          {findings.error && <ErrorNote message={findings.error} onRetry={findings.refetch} />}
          {findings.data &&
            (findings.data.items.length === 0 ? (
              <Empty title="No findings yet">
                Run the analysis from the Findings page after importing billing and
                utilization data.
              </Empty>
            ) : (
              <ul className="list">
                {findings.data.items.map((finding) => (
                  <FindingRow key={finding.id} finding={finding} />
                ))}
              </ul>
            ))}
        </Card>

        <Card
          title="Forecast and freshness"
          subtitle="Projection is per currency; freshness comes from import lineage."
          actions={
            <Link className="btn btn-small" to="/forecasts">
              Forecast detail
            </Link>
          }
        >
          {series ? (
            <div className="forecast-snapshot">
              <span className="muted">
                {series.currency} · {formatDate(series.horizon_start)} –{" "}
                {formatDate(series.horizon_end)}
              </span>
              <strong className="big-number">
                {formatMoney(series.projected_total, series.currency)}
              </strong>
              <span className="muted">
                Likely range {formatMoney(series.projected_lower, series.currency)} –{" "}
                {formatMoney(series.projected_upper, series.currency)} (
                {formatRatioPercent(series.evaluation.interval_quantile, 0)} empirical interval)
              </span>
            </div>
          ) : (
            <Empty title="No forecast run stored">
              Generate one from the Forecasts page. It uses only stored billing rows.
            </Empty>
          )}

          {filters && (
            <dl className="facts">
              <div>
                <dt>Billing window</dt>
                <dd>
                  {filters.window_start
                    ? `${formatDate(filters.window_start)} – ${formatDate(filters.window_end)}`
                    : "No billing rows"}
                </dd>
              </div>
              <div>
                <dt>Last import</dt>
                <dd title={filters.last_import_at ?? undefined}>
                  {filters.last_import_filename ?? "None"} ·{" "}
                  {relativeTime(filters.last_import_at)}
                </dd>
              </div>
              <div>
                <dt>Last billing date</dt>
                <dd>{formatDate(filters.last_billing_date)}</dd>
              </div>
              <div>
                <dt>Synthetic prices</dt>
                <dd>{filters.synthetic_price_count} catalogue entr(ies)</dd>
              </div>
              <div>
                <dt>Imported at</dt>
                <dd>{formatDateTime(filters.last_import_at)}</dd>
              </div>
            </dl>
          )}
          {filters && <Notes items={filters.notes} tone="warn" />}
        </Card>
      </div>

      <Card title="How to read this dashboard" className="quiet">
        <div className="steps">
          <div>
            <span className="step-number">1</span>
            <div>
              <strong>Import</strong>
              <p>Upload billing and utilization CSVs, or use the labelled sample seed.</p>
            </div>
          </div>
          <div>
            <span className="step-number">2</span>
            <div>
              <strong>Analyse</strong>
              <p>Run deterministic rules and a transparent forecast over stored decimals.</p>
            </div>
          </div>
          <div>
            <span className="step-number">3</span>
            <div>
              <strong>Review</strong>
              <p>Record approve, reject or owner-review decisions and export the report.</p>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
