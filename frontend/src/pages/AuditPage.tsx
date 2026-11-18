import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useQuery } from "../api/hooks";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Notes,
  decisionLabel,
  decisionTone,
  riskTone,
} from "../components/ui";
import { formatDate, formatDateTime, formatMoney, titleCase } from "../lib/money";

export function AuditPage() {
  const [decision, setDecision] = useState("");
  const decisions = useQuery(
    (signal) => api.decisions({ decision: decision || undefined, limit: 50 }, signal),
    [decision],
  );
  const reports = useQuery((signal) => api.reports({ limit: 25 }, signal), []);

  const items = decisions.data?.items ?? [];

  return (
    <div className="stack">
      <section className="stat-grid">
        <div className="stat stat-ok">
          <span className="stat-label">Approvals shown</span>
          <span className="stat-value">
            {items.filter((item) => item.decision === "approve").length}
          </span>
          <span className="stat-hint">Append-only records; newest decision wins per finding</span>
        </div>
        <div className="stat stat-danger">
          <span className="stat-label">Rejections shown</span>
          <span className="stat-value">
            {items.filter((item) => item.decision === "reject").length}
          </span>
          <span className="stat-hint">Rejected suggestions stay in the audit trail</span>
        </div>
        <div className="stat stat-warn">
          <span className="stat-label">Owner reviews shown</span>
          <span className="stat-value">
            {items.filter((item) => item.decision === "needs_owner_review").length}
          </span>
          <span className="stat-hint">No resource is changed while a review is pending</span>
        </div>
        <div className="stat">
          <span className="stat-label">Advisor reports stored</span>
          <span className="stat-value">{reports.data?.total ?? "—"}</span>
          <span className="stat-hint">Each report keeps its exact evidence package</span>
        </div>
      </section>

      <Card
        title="Approval history"
        subtitle="Human decisions on findings. Findings and savings estimates are immutable."
        actions={
          <label className="inline-select">
            <span>Decision</span>
            <select value={decision} onChange={(event) => setDecision(event.target.value)}>
              <option value="">All decisions</option>
              <option value="approve">Approve</option>
              <option value="reject">Reject</option>
              <option value="needs_owner_review">Needs owner review</option>
            </select>
          </label>
        }
      >
        {decisions.loading && <Loading rows={4} />}
        {decisions.error && <ErrorNote message={decisions.error} onRetry={decisions.refetch} />}
        {decisions.data && items.length === 0 && (
          <Empty title="No decisions recorded">
            Record one from the <Link to="/findings">Findings</Link> page. Decisions are
            append-only, so nothing is overwritten.
          </Empty>
        )}
        {items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Finding</th>
                  <th scope="col">Resource</th>
                  <th scope="col">Decision</th>
                  <th scope="col">Reviewer</th>
                  <th scope="col">Note</th>
                  <th scope="col" className="num">
                    Monthly savings
                  </th>
                  <th scope="col">Risk</th>
                  <th scope="col">Cost window</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className="nowrap">{formatDateTime(item.created_at)}</td>
                    <td>
                      <span className="mono">finding-{item.finding_id}</span>
                      <span className="muted block">{titleCase(item.finding_type)}</span>
                    </td>
                    <td>
                      <span className="mono">{item.resource_id}</span>
                      <span className="muted block">
                        {item.service} · {item.environment} · {item.project}
                      </span>
                    </td>
                    <td>
                      <Badge tone={decisionTone(item.decision)}>
                        {decisionLabel(item.decision)}
                      </Badge>
                    </td>
                    <td>{item.actor}</td>
                    <td className="note-cell">{item.note ?? "—"}</td>
                    <td className="num">
                      {formatMoney(item.estimated_monthly_savings, item.currency)}
                    </td>
                    <td>
                      <Badge tone={riskTone(item.risk)}>{titleCase(item.risk)}</Badge>
                    </td>
                    <td className="nowrap">
                      {formatDate(item.cost_window_start)} –{" "}
                      {formatDate(item.cost_window_end)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {decisions.data && (
          <p className="muted">
            Showing {items.length} of {decisions.data.total} decision(s), newest first.
          </p>
        )}
        <Notes
          items={[
            "There is no authentication in this build. The reviewer label is self-declared and should be replaced by SSO before production use.",
            "A decision records human intent only. No cloud API is called and no resource is stopped or resized.",
          ]}
          tone="warn"
        />
      </Card>

      <Card
        title="Advisor report history"
        subtitle="Immutable explanations with their validation outcome and evidence hash."
      >
        {reports.loading && <Loading rows={3} />}
        {reports.error && <ErrorNote message={reports.error} onRetry={reports.refetch} />}
        {reports.data && reports.data.items.length === 0 && (
          <Empty title="No advisor reports stored">
            Generate one from the <Link to="/advisor">AI Advisor</Link> page. It works without
            an API key by using the deterministic fallback.
          </Empty>
        )}
        {reports.data && reports.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Created</th>
                  <th scope="col">Status</th>
                  <th scope="col">Mode</th>
                  <th scope="col">AI used</th>
                  <th scope="col">Provider / model</th>
                  <th scope="col">Fallback</th>
                  <th scope="col">Evidence hash</th>
                </tr>
              </thead>
              <tbody>
                {reports.data.items.map((item) => (
                  <tr key={item.id}>
                    <td className="num">{item.id}</td>
                    <td className="nowrap">{formatDateTime(item.created_at)}</td>
                    <td>
                      <Badge tone={item.status === "completed" ? "ok" : "warn"}>
                        {titleCase(item.status)}
                      </Badge>
                    </td>
                    <td>{titleCase(item.mode)}</td>
                    <td>{item.ai_used ? "yes" : "no"}</td>
                    <td>
                      {item.provider ?? "—"} / {item.model ?? "—"}
                    </td>
                    <td>
                      {item.fallback_reason ? (
                        <code>{item.fallback_reason}</code>
                      ) : (
                        "none"
                      )}
                    </td>
                    <td className="mono tiny" title={item.evidence_sha256}>
                      {item.evidence_sha256.slice(0, 16)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
