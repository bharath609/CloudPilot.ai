import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { formatMoney } from "../lib";
import { Badge, Card, ErrorBox, Loading } from "../components/Card";
import type { Resource } from "../types";

const toneFor = (status: string) =>
  status === "idle" ? "danger" : status === "under_utilized" ? "warn" : "ok";

export function ResourcesPage() {
  const { currency } = useCurrency();
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setResources(null);
    api
      .resources(currency)
      .then((d) => alive && setResources(d.resources))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [currency]);

  return (
    <div className="stack">
      <Card title="Resource Health" subtitle={`Resources billed in ${currency}`}>
        {error && <ErrorBox message={error} />}
        {!resources && !error && <Loading what="resources" />}
        {resources && resources.length === 0 && <div className="empty">No resources for {currency}.</div>}
        {resources && resources.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Resource</th>
                <th>Type</th>
                <th>Env</th>
                <th>Region</th>
                <th className="right">CPU</th>
                <th className="right">Mem</th>
                <th className="right">$/hr</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {resources.map((r) => (
                <tr key={r.resource_id}>
                  <td>
                    <div className="strong">{r.name}</div>
                    <div className="muted mono">{r.resource_id}</div>
                  </td>
                  <td>{r.resource_type}</td>
                  <td>{r.environment}</td>
                  <td>{r.region}</td>
                  <td className="right">{r.cpu_pct.toFixed(0)}%</td>
                  <td className="right">{r.memory_pct.toFixed(0)}%</td>
                  <td className="right mono">{formatMoney(r.cost_per_hour, r.currency)}</td>
                  <td><Badge tone={toneFor(r.status)}>{r.status}</Badge></td>
                  <td className="right"><Link to={`/simulation?resource=${r.resource_id}`}>Simulate →</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
