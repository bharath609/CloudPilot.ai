import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { formatDate, formatMoney } from "../lib";
import { Badge, Card, ErrorBox, Loading } from "../components/Card";
import type { Finding, Investigation } from "../types";

export function FindingsPage() {
  const { currency } = useCurrency();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [investigations, setInvestigations] = useState<Record<string, Investigation>>({});

  const load = () => {
    api
      .findings(currency)
      .then((d) => setFindings(d.findings))
      .catch((e) => setError(String(e)));
  };

  useEffect(() => {
    setFindings(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currency]);

  const decide = async (id: string, decision: string) => {
    setBusy(id);
    try {
      await api.decide(id, decision, `${decision} from UI`, "operator");
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const investigate = async (id: string) => {
    setBusy(id);
    try {
      const result = await api.investigate(id);
      setInvestigations((prev) => ({ ...prev, [id]: result }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="stack">
      <Card title="Findings" subtitle={`Waste and rightsizing opportunities in ${currency}`}>
        {error && <ErrorBox message={error} />}
        {!findings && !error && <Loading what="findings" />}
        {findings && findings.length === 0 && <div className="empty">No findings for {currency}.</div>}

        {findings?.map((f) => {
          const inv = investigations[f.id];
          return (
            <div className="finding" key={f.id}>
              <div className="finding-head">
                <div>
                  <div className="finding-title">
                    {f.finding_type.replace(/_/g, " ")} · <span className="mono">{f.resource_id}</span>
                  </div>
                  <div className="muted">
                    Baseline {formatMoney(f.baseline_monthly_cost, f.currency)}/mo · {f.current_sku} → {f.recommended_sku}
                  </div>
                </div>
                <div className="finding-badges">
                  <Badge tone={f.confidence === "high" ? "ok" : f.confidence === "medium" ? "warn" : "muted"}>
                    confidence: {f.confidence}
                  </Badge>
                  <Badge tone={f.risk === "low" ? "ok" : f.risk === "medium" ? "warn" : "danger"}>
                    risk: {f.risk}
                  </Badge>
                </div>
              </div>

              <div className="finding-grid">
                <div>
                  <div className="mini-title">Evidence</div>
                  <ul className="list">{f.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
                <div>
                  <div className="mini-title">Assumptions</div>
                  <ul className="list">{f.assumptions.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
                <div>
                  <div className="mini-title">Warnings</div>
                  <ul className="list warn-list">{f.warnings.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
              </div>

              <div className="finding-actions">
                <button className="btn primary" disabled={busy === f.id} onClick={() => decide(f.id, "accept")}>Accept</button>
                <button className="btn" disabled={busy === f.id} onClick={() => decide(f.id, "reject")}>Reject</button>
                <button className="btn" disabled={busy === f.id} onClick={() => decide(f.id, "defer")}>Defer</button>
                <button className="btn" disabled={busy === f.id} onClick={() => investigate(f.id)}>Investigate</button>
                <Link className="btn ghost" to={`/simulation?resource=${f.resource_id}`}>Simulate →</Link>
                {f.latest_decision && (
                  <span className="decision-chip">
                    Last: <b>{f.latest_decision.decision}</b> by {f.latest_decision.reviewer} · {formatDate(f.latest_decision.created_at)}
                  </span>
                )}
              </div>

              {inv && (
                <div className="investigation">
                  <div className="inv-head">
                    <b>Investigation {inv.investigation_id}</b>
                    <Badge tone={inv.status === "complete" ? "ok" : "warn"}>{inv.status}</Badge>
                    <span className="muted">confidence {inv.confidence}</span>
                  </div>
                  <ol className="steps">
                    {inv.steps.map((s) => (
                      <li key={s.step}><b>{s.name}:</b> {s.finding}</li>
                    ))}
                  </ol>
                  <div className="mini-title">Data gaps</div>
                  <ul className="list warn-list">{inv.data_gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
                  <div className="mini-title">Recommended actions</div>
                  <ul className="list">{inv.recommended_actions.map((g, i) => <li key={i}>{g}</li>)}</ul>
                </div>
              )}
            </div>
          );
        })}
      </Card>
    </div>
  );
}
