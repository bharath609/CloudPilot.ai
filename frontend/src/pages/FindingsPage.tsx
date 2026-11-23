import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAction, useQuery } from "../api/hooks";
import type { DecisionKind, Finding } from "../api/types";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Notes,
  PriceBadge,
  decisionLabel,
  decisionTone,
  riskTone,
} from "../components/ui";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
  sumDecimals,
  titleCase,
} from "../lib/money";
import { useAppState } from "../state/AppState";

const ACTOR_KEY = "cloudpilot.actor";

function DecisionForm({ finding, onRecorded }: { finding: Finding; onRecorded: () => void }) {
  const [decision, setDecision] = useState<DecisionKind>("approve");
  const [actor, setActor] = useState(() => window.localStorage.getItem(ACTOR_KEY) ?? "");
  const [note, setNote] = useState("");

  const submit = useCallback(
    (body: { decision: DecisionKind; actor: string; note: string | null }) =>
      api.decide(finding.id, body),
    [finding.id],
  );
  const action = useAction(submit);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = actor.trim();
    if (!trimmed) return;
    const value = await action.run({ decision, actor: trimmed, note: note.trim() || null });
    if (value) {
      window.localStorage.setItem(ACTOR_KEY, trimmed);
      setNote("");
      onRecorded();
    }
  };

  return (
    <form className="decision-form" onSubmit={handleSubmit}>
      <div className="decision-form-head">
        <strong>Record a review decision</strong>
        <span className="muted">
          Append-only: a newer decision supersedes this one but never erases history.
        </span>
      </div>
      <div className="decision-fields">
        <label>
          <span>Decision</span>
          <select
            value={decision}
            onChange={(event) => setDecision(event.target.value as DecisionKind)}
          >
            <option value="approve">Approve</option>
            <option value="reject">Reject</option>
            <option value="needs_owner_review">Needs owner review</option>
          </select>
        </label>
        <label>
          <span>Reviewer label</span>
          <input
            value={actor}
            onChange={(event) => setActor(event.target.value)}
            placeholder="you@example.test"
            maxLength={80}
            required
          />
        </label>
        <label className="decision-note">
          <span>Note (optional)</span>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why this decision was made"
            maxLength={500}
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={action.pending || !actor.trim()}>
          {action.pending ? "Recording…" : "Record decision"}
        </button>
      </div>
      {action.error && <ErrorNote message={action.error} />}
      <p className="muted tiny">
        There is no authentication yet, so the reviewer label is self-declared and shown in the
        audit trail and exports.
      </p>
    </form>
  );
}

function FindingCard({ finding, onRecorded }: { finding: Finding; onRecorded: () => void }) {
  const scenario = finding.scenario;
  return (
    <article className="finding">
      <header className="finding-head">
        <div>
          <span className="mono finding-resource">{finding.resource_id}</span>
          <h3>{titleCase(finding.finding_type)}</h3>
          <p className="muted">
            {finding.provider} · {finding.service} · {finding.region} ·{" "}
            {finding.environment} · {finding.project}
          </p>
        </div>
        <div className="finding-money">
          <strong>{formatMoney(finding.estimated_monthly_savings, finding.currency)}</strong>
          <span className="muted">per month, {formatPercent(finding.savings_pct)} of baseline</span>
        </div>
      </header>

      <div className="chip-row">
        <Badge tone={riskTone(finding.risk)}>{titleCase(finding.risk)} risk</Badge>
        <Badge tone="neutral">{titleCase(finding.confidence)} confidence</Badge>
        <PriceBadge synthetic={finding.uses_synthetic_prices} />
        <Badge tone={decisionTone(finding.decision?.decision)}>
          {decisionLabel(finding.decision?.decision)}
        </Badge>
      </div>

      <dl className="facts facts-inline">
        <div>
          <dt>Baseline</dt>
          <dd>{formatMoney(finding.baseline_monthly_cost, finding.currency)}/mo</dd>
        </div>
        <div>
          <dt>Proposed</dt>
          <dd>{formatMoney(finding.proposed_monthly_cost, finding.currency)}/mo</dd>
        </div>
        <div>
          <dt>Cost window</dt>
          <dd>
            {formatDate(finding.cost_window_start)} – {formatDate(finding.cost_window_end)}
          </dd>
        </div>
        <div>
          <dt>Observation</dt>
          <dd>
            {finding.observation_days} day(s) · {finding.sample_count} samples
          </dd>
        </div>
        <div>
          <dt>SKU</dt>
          <dd>
            {finding.current_sku ?? "unknown"} → {finding.recommended_sku ?? "n/a"}
          </dd>
        </div>
        <div>
          <dt>Detected</dt>
          <dd>{formatDateTime(finding.created_at)}</dd>
        </div>
      </dl>

      {scenario && (
        <div className="scenario">
          <span className="muted">
            Scenario method: {titleCase(scenario.method)} ·{" "}
            {formatMoney(scenario.estimated_monthly_savings, scenario.currency)} saved per month
          </span>
          <ul>
            {scenario.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {finding.assumptions.length > 0 && <Notes title="Assumptions" items={finding.assumptions} />}
      {finding.warnings.length > 0 && (
        <Notes title="Warnings" items={finding.warnings} tone="warn" />
      )}

      <details className="raw-details">
        <summary>Evidence and metrics</summary>
        <div className="evidence-grid">
          <div>
            <span className="muted">Metrics</span>
            <dl className="facts">
              {Object.entries(finding.metrics).map(([key, value]) => (
                <div key={key}>
                  <dt>{titleCase(key)}</dt>
                  <dd>{value === null ? "—" : String(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div>
            <span className="muted">Price source</span>
            <dl className="facts">
              {Object.entries(finding.price_source).map(([key, value]) => (
                <div key={key}>
                  <dt>{titleCase(key)}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
        <pre>{JSON.stringify(finding.evidence, null, 2)}</pre>
      </details>

      {finding.decision && (
        <p className="decision-current">
          Latest decision:{" "}
          <Badge tone={decisionTone(finding.decision.decision)}>
            {decisionLabel(finding.decision.decision)}
          </Badge>{" "}
          by {finding.decision.actor} on {formatDateTime(finding.decision.created_at)}
          {finding.decision.note ? ` — “${finding.decision.note}”` : ""}
        </p>
      )}

      <DecisionForm finding={finding} onRecorded={onRecorded} />
    </article>
  );
}

export function FindingsPage() {
  const { currency } = useAppState();
  const [findingType, setFindingType] = useState("");
  const findings = useQuery(
    (signal) =>
      api.findings(
        { currency, finding_type: findingType || undefined, limit: 50 },
        signal,
      ),
    [currency, findingType],
  );
  const analysis = useAction(api.runAnalysis);

  const summary = useMemo(() => {
    const items = findings.data?.items ?? [];
    return {
      count: items.length,
      savings: sumDecimals(items.map((item) => item.estimated_monthly_savings)),
    };
  }, [findings.data]);

  const run = async () => {
    // Analyse every currency at once: findings are stored per currency and the
    // list below is filtered by the display currency, so switching currencies
    // never needs a second analysis run.
    const value = await analysis.run({});
    if (value) findings.refetch();
  };

  return (
    <div className="stack">
      <Card
        title="Analysis run"
        subtitle="Rules read only stored billing, utilization and sourced prices. No cloud calls are made."
        actions={
          <div className="row-actions">
            <label className="inline-select">
              <span>Type</span>
              <select
                value={findingType}
                onChange={(event) => setFindingType(event.target.value)}
              >
                <option value="">All findings</option>
                <option value="idle_resource">Idle resources</option>
                <option value="over_provisioned">Over-provisioned</option>
              </select>
            </label>
            <button
              type="button"
              className="btn btn-primary"
              onClick={run}
              disabled={analysis.pending}
            >
              {analysis.pending ? "Running…" : "Run analysis"}
            </button>
          </div>
        }
      >
        {findings.data?.run ? (
          <dl className="facts facts-inline">
            <div>
              <dt>Run</dt>
              <dd>#{findings.data.run.id}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDateTime(findings.data.run.created_at)}</dd>
            </div>
            <div>
              <dt>Findings</dt>
              <dd>{findings.data.total}</dd>
            </div>
            <div>
              <dt>Cost window</dt>
              <dd>
                {formatDate(findings.data.run.cost_window_start)} –{" "}
                {formatDate(findings.data.run.cost_window_end)}
              </dd>
            </div>
            <div>
              <dt>Currency</dt>
              <dd>{findings.data.run.currency ?? "all"}</dd>
            </div>
            <div>
              <dt>Synthetic prices</dt>
              <dd>{findings.data.run.uses_synthetic_prices ? "yes" : "no"}</dd>
            </div>
          </dl>
        ) : (
          <p className="muted">
            No analysis run is stored yet. Import billing and utilization data, then run the
            analysis. The sample seed already includes both files.
          </p>
        )}
        {analysis.error && <ErrorNote message={analysis.error} />}
        {analysis.result && (
          <p className="success-note">
            Analysis completed: {analysis.result.findings.length} finding(s) across all currencies
            in run #{analysis.result.run.id}. Existing findings are unchanged until the next run.
          </p>
        )}
        {findings.data?.run && <Notes items={findings.data.run.notes} />}
      </Card>

      {findings.loading && <Loading rows={4} />}
      {findings.error && <ErrorNote message={findings.error} onRetry={findings.refetch} />}

      {findings.data && findings.data.items.length === 0 && (
        <Card title="No findings in this scope">
          <Empty title="Nothing to review">
            This can mean the rules found no eligible waste, or that no analysis run exists.
            Check the observation windows on the Resource Health page.
          </Empty>
          <div className="quick-links">
            <Link className="btn btn-small" to="/resources">
              Resource health
            </Link>
            <Link className="btn btn-small" to="/imports">
              Imports
            </Link>
          </div>
        </Card>
      )}

      {findings.data && findings.data.items.length > 0 && (
        <>
          <div className="summary-strip">
            <span>
              <strong>{summary.count}</strong> finding(s) shown
            </span>
            <span>
              Estimated savings:{" "}
              <strong>{formatMoney(summary.savings, currency || "USD")}</strong> per month
            </span>
            <span className="muted">
              Savings are estimates with documented assumptions. They are not guaranteed and
              no resource is changed.
            </span>
          </div>
          {findings.data.items.map((finding) => (
            <FindingCard key={finding.id} finding={finding} onRecorded={findings.refetch} />
          ))}
        </>
      )}
    </div>
  );
}
