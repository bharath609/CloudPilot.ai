import { useCallback, useState } from "react";

import { api } from "../api/client";
import { useAction, useQuery } from "../api/hooks";
import type { AdvisorReportDetail } from "../api/types";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Notes,
  riskTone,
} from "../components/ui";
import { formatDateTime, titleCase } from "../lib/money";
import { useAppState } from "../state/AppState";

const FALLBACK_TEXT: Record<string, string> = {
  disabled: "The AI provider is disabled. This explanation was generated deterministically on this machine.",
  missing_api_key: "No API key is configured, so the deterministic explanation is shown.",
  provider_error: "The AI provider returned an error. The deterministic explanation is shown.",
  timeout: "The AI provider timed out. The deterministic explanation is shown.",
  invalid_json: "The AI response was not valid JSON and was rejected.",
  schema_invalid: "The AI response did not match the required schema and was rejected.",
  unknown_finding_id: "The AI referenced a finding that does not exist; the response was rejected.",
  unknown_evidence_id: "The AI referenced evidence that was not provided; the response was rejected.",
  unsupported_numeric_claim: "The AI introduced a number that is not in the evidence package; the response was rejected.",
  missing_priority_finding: "The AI omitted a priority finding; the response was rejected.",
  evidence_package_too_large: "The evidence package exceeded the configured size limit.",
  invalid_response: "The AI response was invalid and was rejected.",
  response_too_large: "The AI response exceeded the configured size limit.",
  insecure_transport: "The configured provider URL is not HTTPS, so no request was sent.",
  validation_failed: "The AI response failed validation; the deterministic explanation is shown.",
};

function ReportView({ report }: { report: AdvisorReportDetail }) {
  const output = report.output;
  return (
    <div className="stack-tight">
      <div className="chip-row">
        <Badge tone={report.ai_used ? "accent" : "neutral"}>
          {report.ai_used ? "AI used" : "Deterministic fallback"}
        </Badge>
        <Badge tone={report.mode === "llm" ? "accent" : "neutral"}>{titleCase(report.mode)} mode</Badge>
        <Badge tone={report.status === "completed" ? "ok" : "warn"}>
          {titleCase(report.status)}
        </Badge>
        {report.provider && <Badge tone="neutral">{report.provider}</Badge>}
        {report.model && <Badge tone="neutral">{report.model}</Badge>}
      </div>

      {report.fallback_reason && (
        <div className="notice">
          <strong>Fallback: {report.fallback_reason}</strong>
          <span>{FALLBACK_TEXT[report.fallback_reason] ?? "The deterministic explanation is shown."}</span>
        </div>
      )}

      {report.fallback_reason === "disabled" && (
        <div className="notice notice-info">
          <strong>The advisor is optional and off by default.</strong>
          <span>
            To enable a free OpenAI-compatible provider, set <code>CLOUDPILOT_LLM_ENABLED=true</code>{" "}
            and a free Groq key as <code>CLOUDPILOT_LLM_API_KEY</code> in <code>.env</code>. The
            default model is <code>llama-3.1-8b-instant</code>. Every response is still validated
            against the evidence package and stored immutably.
          </span>
        </div>
      )}

      {report.validation_errors.length > 0 && (
        <Notes title="Validation errors" items={report.validation_errors} tone="warn" />
      )}

      <section className="report-summary">
        <h3>Executive summary</h3>
        <p>{output.executive_summary}</p>
      </section>

      <div className="report-flags">
        <span className="badge badge-warn">Human review required</span>
        <span className="muted">
          Evidence hash <code>{report.evidence_sha256.slice(0, 16)}…</code> ·{" "}
          {report.attempts} attempt(s) · {report.latency_ms} ms provider latency
        </span>
      </div>

      <section>
        <h3>Priority findings</h3>
        {output.priority_findings.length === 0 ? (
          <Empty title="No prioritized findings in this report" />
        ) : (
          <ol className="priority-list">
            {output.priority_findings.map((item) => (
              <li key={item.finding_id}>
                <div className="priority-head">
                  <code>{item.finding_id}</code>
                  <Badge tone={riskTone(item.risk)}>{titleCase(item.risk)} risk</Badge>
                </div>
                <p>{item.explanation}</p>
                <p className="muted">
                  <strong>Next step:</strong> {item.recommended_next_step}
                </p>
                <div className="chip-row">
                  {item.evidence_ids.map((id) => (
                    <span key={id} className="evidence-chip">
                      {id}
                    </span>
                  ))}
                </div>
                {item.assumptions.length > 0 && (
                  <ul className="assumption-list">
                    {item.assumptions.map((assumption) => (
                      <li key={assumption}>{assumption}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      {output.unknowns.length > 0 && <Notes title="Unknowns" items={output.unknowns} tone="warn" />}
      {report.notes.length > 0 && <Notes items={report.notes} />}
      {report.warnings.length > 0 && (
        <Notes title="Warnings" items={report.warnings} tone="warn" />
      )}

      <details className="raw-details">
        <summary>Stored evidence package (what was eligible to leave the machine)</summary>
        <pre>{JSON.stringify(report.evidence, null, 2)}</pre>
      </details>
      <p className="muted tiny">
        Created {formatDateTime(report.created_at)}. Reports are immutable; generating again
        creates a new record. Monetary values are never produced by the model.
      </p>
    </div>
  );
}

export function AdvisorPage() {
  const { currency } = useAppState();
  const [includeForecast, setIncludeForecast] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const reports = useQuery((signal) => api.reports({ limit: 25 }, signal), []);
  const detail = useQuery(
    (signal) => (selectedId ? api.report(selectedId, signal) : Promise.resolve(null)),
    [selectedId],
  );

  const generate = useAction(
    useCallback(
      (body: Record<string, unknown>) => api.generateReport(body),
      [],
    ),
  );

  const handleGenerate = async () => {
    const value = await generate.run({ include_forecast: includeForecast });
    if (value) {
      setSelectedId(value.id);
      reports.refetch();
    }
  };

  const current = generate.result?.id === selectedId ? generate.result : detail.data;

  return (
    <div className="stack">
      <Card
        title="Generate an explanation"
        subtitle="The advisor may only explain stored findings. It cannot add prices or savings."
        actions={
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleGenerate}
            disabled={generate.pending}
          >
            {generate.pending ? "Generating…" : "Generate report"}
          </button>
        }
      >
        <label className="check">
          <input
            type="checkbox"
            checked={includeForecast}
            onChange={(event) => setIncludeForecast(event.target.checked)}
          />
          <span>Include the latest forecast in the evidence package</span>
        </label>
        <p className="muted">
          The advisor is optional and disabled by default. When disabled, CloudPilot produces a
          deterministic summary from the same validated evidence, so the workflow still works
          without any paid service{currency ? ` (current display currency: ${currency})` : ""}.
        </p>
        {generate.error && <ErrorNote message={generate.error} />}
      </Card>

      <div className="grid grid-2 grid-advisor">
        <Card title="Report history" subtitle="Newest first; each row is immutable.">
          {reports.loading && <Loading />}
          {reports.error && <ErrorNote message={reports.error} onRetry={reports.refetch} />}
          {reports.data && reports.data.items.length === 0 && (
            <Empty title="No reports yet">
              Generate one above. Reports are stored with their exact evidence package.
            </Empty>
          )}
          {reports.data && reports.data.items.length > 0 && (
            <ul className="report-list">
              {reports.data.items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`report-link${item.id === selectedId ? " active" : ""}`}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <span className="report-link-head">
                      <strong>Report #{item.id}</strong>
                      <Badge tone={item.ai_used ? "accent" : "neutral"}>
                        {item.ai_used ? "AI" : "Local"}
                      </Badge>
                    </span>
                    <span className="muted">
                      {formatDateTime(item.created_at)}
                      {item.fallback_reason ? ` · fallback: ${item.fallback_reason}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Selected report" subtitle="Validated output and exact evidence trail.">
          {!selectedId && <Empty title="Select a report">Choose one from the history list.</Empty>}
          {selectedId && detail.loading && <Loading rows={5} />}
          {selectedId && detail.error && (
            <ErrorNote message={detail.error} onRetry={detail.refetch} />
          )}
          {current && <ReportView report={current} />}
        </Card>
      </div>
    </div>
  );
}
