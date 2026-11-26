import { useEffect, useState } from "react";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { formatMoney } from "../lib";
import { Card, ErrorBox, Loading } from "../components/Card";
import type { Costs } from "../types";

export function CostExplorerPage() {
  const { currency } = useCurrency();
  const [granularity, setGranularity] = useState("daily");
  const [data, setData] = useState<Costs | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    api
      .costs(currency, granularity)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [currency, granularity]);

  const series = data?.series ?? [];
  const max = Math.max(1, ...series.map((p) => Number(p.amount)));
  const shown = granularity === "daily" ? series.slice(-30) : series;

  return (
    <div className="stack">
      <Card
        title="Cost Explorer"
        subtitle={`Spend over time in ${currency} — no FX conversion`}
        right={
          <div className="segmented">
            <button className={granularity === "daily" ? "seg active" : "seg"} onClick={() => setGranularity("daily")}>
              Daily
            </button>
            <button className={granularity === "monthly" ? "seg active" : "seg"} onClick={() => setGranularity("monthly")}>
              Monthly
            </button>
          </div>
        }
      >
        {error && <ErrorBox message={error} />}
        {!data && !error && <Loading what="costs" />}
        {data && (
          <>
            <div className="chart">
              {shown.map((p) => (
                <div className="chart-col" key={p.period} title={`${p.period}: ${formatMoney(p.amount, currency)}`}>
                  <div className="chart-bar" style={{ height: `${(Number(p.amount) / max) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="chart-axis">
              <span>{shown[0]?.period}</span>
              <span>{shown[shown.length - 1]?.period}</span>
            </div>

            <table className="table">
              <thead>
                <tr>
                  <th>Period</th>
                  <th className="right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {series
                  .slice()
                  .reverse()
                  .slice(0, 20)
                  .map((p) => (
                    <tr key={p.period}>
                      <td>{p.period}</td>
                      <td className="right mono">{formatMoney(p.amount, currency)}</td>
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
