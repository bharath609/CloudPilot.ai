import { useEffect, useState } from "react";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { formatMoney } from "../lib";
import { Card, ErrorBox, Loading, Stat } from "../components/Card";
import type { Forecast } from "../types";

export function ForecastsPage() {
  const { currency } = useCurrency();
  const [data, setData] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    api
      .forecasts(currency)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [currency]);

  return (
    <div className="stack">
      <Card title="Forecasts" subtitle={`Empirical 14-day projection in ${currency} (no FX)`}>
        {error && <ErrorBox message={error} />}
        {!data && !error && <Loading what="forecast" />}
        {data && data.metrics && (
          <>
            <div className="stats-grid">
              <Stat label="MAE" value={data.metrics.mae.toFixed(2)} hint={currency} />
              <Stat label="RMSE" value={data.metrics.rmse.toFixed(2)} hint={currency} />
              <Stat label="MAPE" value={`${data.metrics.mape.toFixed(1)}%`} hint="7-day moving average" />
              <Stat label="HORIZON" value={`${data.forecast.length} days`} hint="Flat MA projection" />
            </div>

            <Sparkline
              history={data.history.map((h) => Number(h.amount))}
              forecast={data.forecast.map((f) => Number(f.amount))}
            />

            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th className="right">Forecast</th>
                  <th className="right">Low</th>
                  <th className="right">High</th>
                </tr>
              </thead>
              <tbody>
                {data.forecast.map((f) => (
                  <tr key={f.date}>
                    <td>{f.date}</td>
                    <td className="right mono">{formatMoney(f.amount, currency)}</td>
                    <td className="right mono muted">{formatMoney(f.low ?? 0, currency)}</td>
                    <td className="right mono muted">{formatMoney(f.high ?? 0, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>
    </div>
  );
}

function Sparkline({ history, forecast }: { history: number[]; forecast: number[] }) {
  const all = [...history, ...forecast];
  const max = Math.max(1, ...all);
  const min = Math.min(0, ...all);
  const W = 800;
  const H = 180;
  const pad = 10;
  const x = (i: number) => pad + (i / Math.max(1, all.length - 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - min) / Math.max(1, max - min)) * (H - 2 * pad);

  const histPath = history.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const fcPath = forecast
    .map((v, i) => `${i === 0 ? "M" : "L"}${x(history.length + i).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");

  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <path d={histPath} fill="none" stroke="#38bdf8" strokeWidth="2" />
      <path d={fcPath} fill="none" stroke="#a78bfa" strokeWidth="2" strokeDasharray="5 4" />
    </svg>
  );
}
