import { useEffect, useState } from "react";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { Badge, Card, ErrorBox, Loading } from "../components/Card";
import type { AnomalyResult, PolicyResult, Resource } from "../types";

function AnomalyCard({ a }: { a: AnomalyResult }) {
  return (
    <div className="anomaly">
      <div className="finding-head">
        <div className="finding-title">{a.kind} · {a.currency}</div>
        <Badge tone={a.detected ? "danger" : "ok"}>{a.detected ? "detected" : "normal"}</Badge>
      </div>
      <p>{a.description}</p>
      <div className="facts compact">
        <div className="fact"><span>Baseline</span><b>{a.baseline}</b></div>
        <div className="fact"><span>Current</span><b>{a.current}</b></div>
        <div className="fact"><span>Change</span><b>{a.change_pct}%</b></div>
        <div className="fact"><span>Confidence</span><b>{a.confidence}</b></div>
      </div>
      {a.data_gaps.length > 0 && (
        <>
          <div className="mini-title">Data gaps</div>
          <ul className="list warn-list">{a.data_gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
        </>
      )}
      {a.recommended_actions.length > 0 && (
        <>
          <div className="mini-title">Recommended actions</div>
          <ul className="list">{a.recommended_actions.map((g, i) => <li key={i}>{g}</li>)}</ul>
        </>
      )}
    </div>
  );
}

export function AnomaliesPage() {
  const { currency } = useCurrency();
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [resourceId, setResourceId] = useState("");
  const [spend, setSpend] = useState<AnomalyResult | null>(null);
  const [capacity, setCapacity] = useState<AnomalyResult | null>(null);
  const [perf, setPerf] = useState<AnomalyResult | null>(null);
  const [policy, setPolicy] = useState<PolicyResult | null>(null);
  const [actionType, setActionType] = useState("stop_resource");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .resources(currency)
      .then((d) => {
        if (!alive) return;
        setResources(d.resources);
        if (d.resources.length) setResourceId(d.resources[0].resource_id);
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [currency]);

  const runSpend = async () => {
    try {
      setSpend(await api.anomalySpending(currency));
    } catch (e) {
      setError(String(e));
    }
  };
  const runCapacity = async () => {
    if (!resourceId) return;
    try {
      setCapacity(await api.anomalyCapacity(resourceId));
    } catch (e) {
      setError(String(e));
    }
  };
  const runPerf = async () => {
    if (!resourceId) return;
    try {
      setPerf(await api.anomalyPerformance(resourceId));
    } catch (e) {
      setError(String(e));
    }
  };
  const runPolicy = async () => {
    try {
      setPolicy(
        await api.policy({
          action_type: actionType,
          resource_id: resourceId,
          environment: "production",
          requesting_user: "operator",
          spending_delta: 0,
        })
      );
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="stack">
      <Card title="Predictive Intelligence" subtitle={`Anomaly detection and policy checks in ${currency}`}>
        {error && <ErrorBox message={error} />}
        {!resources && !error && <Loading what="resources" />}

        {resources && (
          <>
            <div className="form-grid">
              <label className="field">
                <span>Resource</span>
                <select value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
                  {resources.map((r) => (
                    <option key={r.resource_id} value={r.resource_id}>
                      {r.name} · {r.resource_id}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Policy action</span>
                <select value={actionType} onChange={(e) => setActionType(e.target.value)}>
                  <option value="read_cloud_metrics">read_cloud_metrics</option>
                  <option value="stop_resource">stop_resource</option>
                  <option value="resize_resource">resize_resource</option>
                  <option value="delete_resource">delete_resource</option>
                </select>
              </label>
            </div>

            <div className="button-row">
              <button className="btn primary" onClick={runSpend}>Detect spending anomaly</button>
              <button className="btn" onClick={runCapacity}>Detect capacity risk</button>
              <button className="btn" onClick={runPerf}>Detect performance degradation</button>
              <button className="btn" onClick={runPolicy}>Evaluate policy</button>
            </div>

            {policy && (
              <div className="anomaly">
                <div className="finding-head">
                  <div className="finding-title">Policy · {policy.action_type}</div>
                  <Badge tone={policy.allowed ? "ok" : "danger"}>{policy.allowed ? "allowed" : "blocked"}</Badge>
                </div>
                <div className="muted">
                  rule: {policy.rule_id ?? "—"} · approval required: {String(policy.requires_approval)}
                </div>
                {policy.violations.length > 0 && (
                  <ul className="list warn-list">{policy.violations.map((v, i) => <li key={i}>{v}</li>)}</ul>
                )}
              </div>
            )}

            <div className="anomaly-grid">
              {spend && <AnomalyCard a={spend} />}
              {capacity && <AnomalyCard a={capacity} />}
              {perf && <AnomalyCard a={perf} />}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
