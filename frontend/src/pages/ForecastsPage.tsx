import { useCallback, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import { useAction, useQuery } from "../api/hooks";
import { CHART, ChartLegend, MoneyTooltip, axisProps } from "../components/charts";
import { Card, Empty, ErrorNote, Field, Loading, Notes, Stat } from "../components/ui";
import {
  compactMoney,
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
  plotValue,
  titleCase,
} from "../lib/money";
import { useAppState } from "../state/AppState";

export function ForecastsPage() {
  const { currency } = useAppState();
  const [method, setMethod] = useState<"seasonal_naive" | "moving_average">("seasonal_naive");
  const [horizon, setHorizon] = useState(30);
  const [holdout, setHoldout] = useState(14);
  const [movingAverageDays, setMovingAverageDays] = useState(7);
  const [seriesCurrency, setSeriesCurrency] = useState("");

  const latest = useQuery((signal) => api.latestForecast(signal), []);
  const run = useAction(
    useCallback(
      (body: Record<string, unknown>) => api.runForecast(body),
      [],
    ),
  );

  const result = run.result ?? latest.data;
  const seriesList = result?.series ?? [];
  const series =
    seriesList.find((item) => item.currency === seriesCurrency) ??
    seriesList.find((item) => item.currency === currency) ??
    seriesList[0];

  const chartData = useMemo(
    () =>
      (series?.points ?? []).map((point) => ({
        label: point.period,
        exact: point.predicted_cost,
        lower: point.lower_bound,
        upper: point.upper_bound,
        currency: series?.currency,
        value: plotValue(point.predicted_cost),
        band: [plotValue(point.lower_bound), plotValue(point.upper_bound)],
      })),
    [series],
  );

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = await run.run({
      method,
      horizon_days: horizon,
      holdout_days: holdout,
      moving_average_days: movingAverageDays,
      currency: currency || undefined,
    });
    if (value) {
      setSeriesCurrency(currency || value.series[0]?.currency || "");
      latest.refetch();
    }
  };

  return (
    <div className="stack">
      <Card
        title="Run a forecast"
        subtitle="Deterministic baseline over stored daily spend. No external model or FX conversion."
      >
        <form className="forecast-form" onSubmit={submit}>
          <Field label="Method" hint="Seasonal naive repeats the same weekday; moving average smooths.">
            <select
              value={method}
              onChange={(event) =>
                setMethod(event.target.value as "seasonal_naive" | "moving_average")
              }
            >
              <option value="seasonal_naive">Seasonal naive (7-day season)</option>
              <option value="moving_average">Moving average</option>
            </select>
          </Field>
          <Field label="Horizon (days)" hint="1–90">
            <input
              type="number"
              min={1}
              max={90}
              value={horizon}
              onChange={(event) => setHorizon(Number(event.target.value))}
            />
          </Field>
          <Field label="Holdout (days)" hint="Chronological evaluation window">
            <input
              type="number"
              min={1}
              max={60}
              value={holdout}
              onChange={(event) => setHoldout(Number(event.target.value))}
            />
          </Field>
          <Field label="Moving average window" hint="Used by the moving-average method">
            <input
              type="number"
              min={1}
              max={60}
              value={movingAverageDays}
              onChange={(event) => setMovingAverageDays(Number(event.target.value))}
            />
          </Field>
          <button type="submit" className="btn btn-primary" disabled={run.pending}>
            {run.pending ? "Forecasting…" : "Run forecast"}
          </button>
        </form>
        {run.error && <ErrorNote message={run.error} />}
        {latest.error && <ErrorNote message={latest.error} onRetry={latest.refetch} />}
      </Card>

      {latest.loading && !run.result && <Loading rows={4} />}

      {!latest.loading && seriesList.length === 0 && (
        <Card title="No forecast stored">
          <Empty title="Generate a forecast to see the projection">
            At least 28 days of billing history are required. Import billing data first.
          </Empty>
        </Card>
      )}

      {result && seriesList.length > 1 && (
        <div className="chip-row">
          <span className="muted">Currency series:</span>
          {seriesList.map((item) => (
            <button
              key={item.currency}
              type="button"
              className={`chip-button${item.currency === series?.currency ? " active" : ""}`}
              onClick={() => setSeriesCurrency(item.currency)}
            >
              {item.currency}
            </button>
          ))}
        </div>
      )}

      {result && result.run && series && (
        <>
          <section className="stat-grid">
            <Stat
              label="Projected total"
              value={formatMoney(series.projected_total, series.currency)}
              hint={`${formatDate(series.horizon_start)} – ${formatDate(series.horizon_end)}`}
              tone="accent"
            />
            <Stat
              label="Lower bound"
              value={formatMoney(series.projected_lower, series.currency)}
              hint={`Empirical ${formatPercent(series.evaluation.interval_quantile, 0)} interval`}
            />
            <Stat
              label="Upper bound"
              value={formatMoney(series.projected_upper, series.currency)}
              hint="Not a guarantee; based on held-out residuals"
              tone="warn"
            />
            <Stat
              label="Held-out MAPE"
              value={
                series.evaluation.mape_pct ? formatPercent(series.evaluation.mape_pct, 2) : "n/a"
              }
              hint={`${series.evaluation.evaluated_points} point(s) evaluated`}
            />
          </section>

          <Card
            title="Projection and uncertainty band"
            subtitle={`Method ${titleCase(result.run.method)} · history ${formatDate(
              series.history_start,
            )} – ${formatDate(series.history_end)}`}
          >
            {chartData.length === 0 ? (
              <Empty title="No forecast points" />
            ) : (
              <>
                <div className="chart-box">
                  <ResponsiveContainer width="100%" height={320}>
                    <ComposedChart
                      data={chartData}
                      margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                    >
                      <CartesianGrid stroke={CHART.grid} strokeDasharray="3 4" vertical={false} />
                      <XAxis
                        dataKey="label"
                        {...axisProps}
                        minTickGap={26}
                        tickFormatter={(value: string) => value.slice(5)}
                      />
                      <YAxis
                        {...axisProps}
                        width={68}
                        tickFormatter={(value: number) =>
                          compactMoney(String(value), series.currency)
                        }
                      />
                      <Tooltip content={<MoneyTooltip currency={series.currency} />} />
                      <Area
                        dataKey="band"
                        stroke="none"
                        fill={CHART.band}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={CHART.accent}
                        strokeWidth={2.4}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey={(row: { band: number[] }) => row.band[0]}
                        stroke={CHART.lower}
                        strokeWidth={1.2}
                        strokeDasharray="4 4"
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey={(row: { band: number[] }) => row.band[1]}
                        stroke={CHART.upper}
                        strokeWidth={1.2}
                        strokeDasharray="4 4"
                        dot={false}
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <ChartLegend
                  items={[
                    { color: CHART.accent, label: "Predicted daily spend" },
                    { color: CHART.lower, label: "Lower bound" },
                    { color: CHART.upper, label: "Upper bound" },
                  ]}
                />
              </>
            )}
          </Card>

          <div className="grid grid-2">
            <Card title="Held-out evaluation" subtitle="Errors are measured on data withheld from fitting.">
              <dl className="facts">
                <div>
                  <dt>Method</dt>
                  <dd>{titleCase(series.evaluation.method)}</dd>
                </div>
                <div>
                  <dt>History / training days</dt>
                  <dd>
                    {series.evaluation.history_days} / {series.evaluation.train_days}
                  </dd>
                </div>
                <div>
                  <dt>Holdout days</dt>
                  <dd>{series.evaluation.holdout_days}</dd>
                </div>
                <div>
                  <dt>MAE</dt>
                  <dd>{formatMoney(series.evaluation.mae, series.currency)}</dd>
                </div>
                <div>
                  <dt>RMSE</dt>
                  <dd>{formatMoney(series.evaluation.rmse, series.currency)}</dd>
                </div>
                <div>
                  <dt>Bias</dt>
                  <dd>{formatMoney(series.evaluation.bias, series.currency)}</dd>
                </div>
                <div>
                  <dt>MAPE</dt>
                  <dd>
                    {series.evaluation.mape_pct
                      ? formatPercent(series.evaluation.mape_pct, 2)
                      : "n/a"}{" "}
                    {series.evaluation.mape_excluded_points > 0 &&
                      `(${series.evaluation.mape_excluded_points} zero-day point(s) excluded)`}
                  </dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>{titleCase(series.evaluation.confidence)}</dd>
                </div>
                <div>
                  <dt>Interval width</dt>
                  <dd>{formatMoney(series.evaluation.interval_width, series.currency)}</dd>
                </div>
              </dl>
              {series.evaluation.warnings.length > 0 && (
                <Notes title="Evaluation warnings" items={series.evaluation.warnings} tone="warn" />
              )}
            </Card>

            <Card title="Run detail" subtitle="What was used and what was assumed.">
              <dl className="facts">
                <div>
                  <dt>Run</dt>
                  <dd>#{result.run.id}</dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{formatDateTime(result.run.created_at)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{titleCase(result.run.status)}</dd>
                </div>
                <div>
                  <dt>Granularity</dt>
                  <dd>{titleCase(result.run.granularity)}</dd>
                </div>
                <div>
                  <dt>Series</dt>
                  <dd>{result.run.series_count}</dd>
                </div>
                <div>
                  <dt>Duration</dt>
                  <dd>{result.run.duration_ms} ms</dd>
                </div>
              </dl>
              <Notes items={series.notes} />
              {result.run.warnings.length > 0 && (
                <Notes title="Run warnings" items={result.run.warnings} tone="warn" />
              )}
              <Notes items={result.run.notes} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
