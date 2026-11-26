import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { formatMoney } from "../lib";
import { Badge, Card, ErrorBox, Loading, Stat } from "../components/Card";
import type { Finding, Resource, SimulationResult } from "../types";

export function SimulationLabPage() {
  const { currency } = useCurrency();
  const [params, setParams] = useSearchParams();
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [resourceId, setResourceId] = useState<string>(params.get("resource") ?? "");
  const [scenario, setScenario] = useState<"stop" | "rightsize">("stop");
  const [retention, setRetention] = useState(0);
  const [ratio, setRatio] = useState(0.5);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setResources(null);
    setResult(null);
    Promise.all([api.resources(currency), api.findings(currency)])
      .then(([r, f]) => {
        if (!alive) return;
        setResources(r.resources);
        setFindings(f.findings);
        if (!resourceId && r.resources.length) setResourceId(r.resources[0].resource_id);
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currency]);

  const baseline = useMemo(() => {
    const f = findings.find((x) => x.resource_id === resourceId);
    return f?.baseline_monthly_cost;
  }, [findings, resourceId]);

  const run = async () => {
    if (!resourceId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.simulate({
        resource_id: resourceId,
        scenario,
        utilization_retention: retention,
        sku_ratio: ratio,
      });
      setResult(r);
      setParams({ resource: resourceId });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <Card
        title="Simulation Lab"
        subtitle="What-if projections from stored findings — isolated from production"
        right={<Badge tone="info">No real changes applied</Badge>}
      >
        {error && <ErrorBox message={error} />}
        {!resources && !error && <Loading what="resources" />}

        {resources && (
          <>
            <div className="form-grid">
              <label className="field">
                <span>Resource ({currency})</span>
                <select value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
                  {resources.map((r) => (
                    <option key={r.resource_id} value={r.resource_id}>
                      {r.name} · {r.resource_id}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Scenario</span>
                <select value={scenario} onChange={(e) => setScenario(e.target.value as any)}>
                  <option value="stop">Stop resource</option>
                  <option value="rightsize">Rightsize to smaller SKU</option>
                </select>
              </label>

              {scenario === "stop" ? (
                <label className="field">
                  <span>Utilization retention: {retention}%</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={retention}
                    onChange={(e) => setRetention(Number(e.target.value))}
                  />
                </label>
              ) : (
                <label className="field">
                  <span>SKU price ratio: {ratio.toFixed(2)}×</span>
                  <input
                    type="range"
                    min={0.1}
                    max={2}
                    step={0.05}
                    value={ratio}
                    onChange={(e) => setRatio(Number(e.target.value))}
                  />
                </label>
              )}
            </div>

            <div className="row-between">
              <div className="muted">
                {baseline ? `Baseline from finding: ${formatMoney(baseline, currency)}/mo` : "No stored baseline for this resource."}
              </div>
              <button className="btn primary" onClick={run} disabled={busy || !resourceId}>
                {busy ? "Simulating…" : "Run simulation"}
              </button>
            </div>

            {result && (
              <>
                <div className="stats-grid">
                  <Stat label="BASELINE" value={formatMoney(result.baseline_monthly_cost, result.currency)} hint="per month" />
                  <Stat label="PROJECTED" value={formatMoney(result.projected_monthly_cost, result.currency)} hint="per month" />
                  <Stat label="SAVINGS" value={formatMoney(result.projected_monthly_savings, result.currency)} hint="per month" />
                  <Stat label="CONFIDENCE" value={result.confidence} hint={`${result.assumptions.length} assumptions`} />
                </div>

                <div className="two-col">
                  <div>
                    <h3 className="section-title">Assumptions</h3>
                    <ul className="list">{result.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
                  </div>
                  <div>
                    <h3 className="section-title">Warnings</h3>
                    <ul className="list warn-list">{result.warnings.map((a, i) => <li key={i}>{a}</li>)}</ul>
                    <div className="inline-note">{result.note}</div>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
