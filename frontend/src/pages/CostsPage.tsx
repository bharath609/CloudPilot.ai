import { useMemo, useState } from "react";
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
import { CHART, MoneyTooltip, axisProps } from "../components/charts";
import {
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Notes,
} from "../components/ui";
import {
  compactMoney,
  formatDate,
  formatMoney,
  formatPercent,
  plotValue,
  titleCase,
} from "../lib/money";
import { useAppState } from "../state/AppState";

const DIMENSIONS = ["service", "project", "region", "environment", "provider", "account", "resource"];

export function CostsPage() {
  const { currency, filters } = useAppState();
  const [dimension, setDimension] = useState("service");
  const [granularity, setGranularity] = useState<"day" | "month">("day");
  const [provider, setProvider] = useState("");
  const [service, setService] = useState("");
  const [project, setProject] = useState("");
  const [region, setRegion] = useState("");
  const [environment, setEnvironment] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const params = useMemo(
    () => ({
      currency,
      provider: provider || undefined,
      service: service || undefined,
      project: project || undefined,
      region: region || undefined,
      environment: environment || undefined,
      start: start || undefined,
      end: end || undefined,
    }),
    [currency, provider, service, project, region, environment, start, end],
  );

  const summary = useQuery((signal) => api.summary(params, signal), [params]);
  const breakdown = useQuery(
    (signal) => api.breakdown({ ...params, dimension, limit: 50 }, signal),
    [params, dimension],
  );
  const trends = useQuery(
    (signal) => api.trends({ ...params, granularity }, signal),
    [params, granularity],
  );

  const chartData = (trends.data?.points ?? []).map((point) => ({
    label: point.bucket,
    exact: point.amount,
    currency: point.currency,
    value: plotValue(point.amount),
    detail: `${point.row_count} row(s)`,
  }));

  const reset = () => {
    setProvider("");
    setService("");
    setProject("");
    setRegion("");
    setEnvironment("");
    setStart("");
    setEnd("");
    setDimension("service");
    setGranularity("day");
  };

  const activeFilters = [
    provider && `provider ${provider}`,
    service && `service ${service}`,
    project && `project ${project}`,
    region && `region ${region}`,
    environment && `environment ${environment}`,
    start && `from ${start}`,
    end && `to ${end}`,
  ].filter(Boolean) as string[];

  return (
    <div className="stack">
      <Card
        title="Filters"
        subtitle="Options come from stored rows, so a choice can never be silently empty."
        actions={
          <button type="button" className="btn btn-small btn-ghost" onClick={reset}>
            Reset
          </button>
        }
      >
        {!filters && <Loading rows={2} />}
        {filters && (
          <div className="filter-grid">
            <Field label="Provider">
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                <option value="">All providers</option>
                {filters.providers.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Service">
              <select value={service} onChange={(event) => setService(event.target.value)}>
                <option value="">All services</option>
                {filters.services.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Project">
              <select value={project} onChange={(event) => setProject(event.target.value)}>
                <option value="">All projects</option>
                {filters.projects.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Region">
              <select value={region} onChange={(event) => setRegion(event.target.value)}>
                <option value="">All regions</option>
                {filters.regions.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Environment">
              <select
                value={environment}
                onChange={(event) => setEnvironment(event.target.value)}
              >
                <option value="">All environments</option>
                {filters.environments.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Start date">
              <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
            </Field>
            <Field label="End date">
              <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
            </Field>
          </div>
        )}
        {activeFilters.length > 0 && (
          <p className="active-filters">Active: {activeFilters.join(" · ")}</p>
        )}
      </Card>

      <section className="stat-grid">
        {summary.loading && <Loading rows={1} />}
        {summary.error && <ErrorNote message={summary.error} onRetry={summary.refetch} />}
        {summary.data && (
          <>
            <div className="stat stat-accent">
              <span className="stat-label">Spend in scope</span>
              <span className="stat-value">
                {summary.data.totals.length === 0
                  ? "0"
                  : summary.data.totals
                      .map((item) => formatMoney(item.amount, item.currency))
                      .join(" + ")}
              </span>
              <span className="stat-hint">
                {summary.data.totals.length > 1
                  ? "Currencies are shown separately and never added together."
                  : "Exact decimal total for the filtered window."}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Window</span>
              <span className="stat-value">
                {summary.data.window.days ?? 0} day(s)
              </span>
              <span className="stat-hint">
                {formatDate(summary.data.window.start)} – {formatDate(summary.data.window.end)}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Rows counted</span>
              <span className="stat-value">{summary.data.row_count.toLocaleString("en")}</span>
              <span className="stat-hint">
                {summary.data.excluded_duplicate_rows} duplicate row(s) excluded
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Imports represented</span>
              <span className="stat-value">{summary.data.import_count}</span>
              <span className="stat-hint">Import IDs {summary.data.import_ids.join(", ") || "—"}</span>
            </div>
          </>
        )}
      </section>

      <Card
        title="Spend over time"
        subtitle="Tooltips show the exact stored decimal. Chart scale is approximate."
        actions={
          <div className="segmented" role="group" aria-label="Granularity">
            <button
              type="button"
              className={granularity === "day" ? "active" : ""}
              onClick={() => setGranularity("day")}
            >
              Daily
            </button>
            <button
              type="button"
              className={granularity === "month" ? "active" : ""}
              onClick={() => setGranularity("month")}
            >
              Monthly
            </button>
          </div>
        }
      >
        {trends.loading && <Loading />}
        {trends.error && <ErrorNote message={trends.error} onRetry={trends.refetch} />}
        {trends.data &&
          (chartData.length === 0 ? (
            <Empty title="No spend matches these filters">
              Widen the date range or clear a filter.
            </Empty>
          ) : (
            <div className="chart-box">
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="costs-spend" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={CHART.accent} stopOpacity={0.42} />
                      <stop offset="100%" stopColor={CHART.accent} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={CHART.grid} strokeDasharray="3 4" vertical={false} />
                  <XAxis
                    dataKey="label"
                    {...axisProps}
                    minTickGap={26}
                    tickFormatter={(value: string) =>
                      granularity === "month" ? value.slice(0, 7) : value.slice(5)
                    }
                  />
                  <YAxis
                    {...axisProps}
                    width={68}
                    tickFormatter={(value: number) =>
                      compactMoney(String(value), currency || undefined)
                    }
                  />
                  <Tooltip content={<MoneyTooltip currency={currency} />} />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke={CHART.accent}
                    strokeWidth={2}
                    fill="url(#costs-spend)"
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ))}
        {trends.data && <Notes items={trends.data.notes} />}
      </Card>

      <Card
        title="Breakdown"
        subtitle="Share is computed only within one currency."
        actions={
          <label className="inline-select">
            <span>Group by</span>
            <select value={dimension} onChange={(event) => setDimension(event.target.value)}>
              {DIMENSIONS.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
        }
      >
        {breakdown.loading && <Loading />}
        {breakdown.error && <ErrorNote message={breakdown.error} onRetry={breakdown.refetch} />}
        {breakdown.data &&
          (breakdown.data.items.length === 0 ? (
            <Empty title="Nothing to break down" />
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">{titleCase(dimension)}</th>
                      <th scope="col">Currency</th>
                      <th scope="col" className="num">
                        Amount
                      </th>
                      <th scope="col" className="num">
                        Share
                      </th>
                      <th scope="col" className="num">
                        Rows
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {breakdown.data.items.map((item) => (
                      <tr key={`${item.key}-${item.currency}`}>
                        <td className="mono">{item.key}</td>
                        <td>{item.currency}</td>
                        <td className="num">{formatMoney(item.amount, item.currency)}</td>
                        <td className="num">{formatPercent(item.share_pct)}</td>
                        <td className="num">{item.row_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {breakdown.data.items_truncated && (
                <p className="muted">
                  Showing the top 50 groups of {breakdown.data.total_groups}. Narrow the filters
                  to see the rest.
                </p>
              )}
              <Notes items={breakdown.data.notes} />
            </>
          ))}
      </Card>
    </div>
  );
}
