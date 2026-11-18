import { useCallback, useRef, useState } from "react";

import { api } from "../api/client";
import { useAction, useQuery } from "../api/hooks";
import type { ImportResult, ValidationIssue } from "../api/types";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Notes,
} from "../components/ui";
import { formatDate, formatDateTime, titleCase } from "../lib/money";
import { useAppState } from "../state/AppState";

function statusTone(status: string) {
  if (status === "valid") return "ok" as const;
  if (status === "valid_with_warnings" || status === "partial") return "warn" as const;
  return "danger" as const;
}

function IssueTable({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) return <p className="muted">No row-level issues were recorded.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col" className="num">
              Row
            </th>
            <th scope="col">Severity</th>
            <th scope="col">Code</th>
            <th scope="col">Column</th>
            <th scope="col">Message</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr key={`${issue.row_number}-${issue.code}-${index}`}>
              <td className="num">{issue.row_number}</td>
              <td>
                <Badge tone={issue.severity === "error" ? "danger" : "warn"}>
                  {titleCase(issue.severity)}
                </Badge>
              </td>
              <td>
                <code>{issue.code}</code>
              </td>
              <td>{issue.column ?? "—"}</td>
              <td>{issue.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UploadCard({
  kind,
  title,
  description,
  onUploaded,
}: {
  kind: "billing" | "utilization";
  title: string;
  description: string;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [force, setForce] = useState(false);
  const [outcome, setOutcome] = useState<ImportResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useAction(
    useCallback(
      (target: "billing" | "utilization", selected: File, forceImport: boolean) =>
        api.upload(target, selected, forceImport),
      [],
    ),
  );

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) return;
    const result = await upload.run(kind, file, force);
    if (result) {
      setOutcome(result);
      setFile(null);
      setForce(false);
      if (inputRef.current) inputRef.current.value = "";
      onUploaded();
    }
  };

  return (
    <Card title={title} subtitle={description}>
      <form className="upload-form" onSubmit={handleSubmit}>
        <Field label="CSV file" hint="UTF-8, up to the configured upload size limit.">
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => {
              setOutcome(null);
              setFile(event.target.files?.[0] ?? null);
            }}
            required
          />
        </Field>
        <label className="check">
          <input
            type="checkbox"
            checked={force}
            onChange={(event) => setForce(event.target.checked)}
          />
          <span>Re-import even if this exact file was uploaded before</span>
        </label>
        <button type="submit" className="btn btn-primary" disabled={!file || upload.pending}>
          {upload.pending ? "Uploading…" : "Upload and validate"}
        </button>
      </form>
      {upload.error && <ErrorNote message={upload.error} />}
      {outcome && (
        <div className="upload-result">
          <div className="chip-row">
            <Badge tone={statusTone(outcome.status)}>{titleCase(outcome.status)}</Badge>
            <span className="muted">
              Import #{outcome.id} · {outcome.accepted_row_count} accepted ·{" "}
              {outcome.rejected_row_count} rejected · {outcome.warning_count} warning(s)
            </span>
          </div>
          {outcome.message && <p>{outcome.message}</p>}
          <p className="muted tiny">
            SHA-256 <code>{outcome.content_sha256}</code>
          </p>
          <IssueTable issues={outcome.issues} />
          {outcome.issues_truncated && (
            <p className="muted">Additional issues were truncated in this preview.</p>
          )}
        </div>
      )}
    </Card>
  );
}

export function ImportsPage() {
  const { reloadFilters } = useAppState();
  const [kind, setKind] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);

  const imports = useQuery(
    (signal) => api.imports({ kind: kind || undefined, limit: 50 }, signal),
    [kind, nonce],
  );
  const detail = useQuery(
    (signal) => (selectedId ? api.importDetail(selectedId, signal) : Promise.resolve(null)),
    [selectedId],
  );
  const issues = useQuery(
    (signal) => (selectedId ? api.importIssues(selectedId, signal) : Promise.resolve(null)),
    [selectedId],
  );

  const refresh = () => {
    setNonce((value) => value + 1);
    reloadFilters();
  };

  return (
    <div className="stack">
      <div className="grid grid-2">
        <UploadCard
          kind="billing"
          title="Billing CSV"
          description="Generic spend export: usage_date, provider, cost_amount, currency and related columns."
          onUploaded={refresh}
        />
        <UploadCard
          kind="utilization"
          title="Utilization CSV"
          description="CPU and memory samples keyed by resource_id, used by the deterministic rules."
          onUploaded={refresh}
        />
      </div>

      <Card
        title="Import history"
        subtitle="Every attempt is stored, including rejected files, with a content hash."
        actions={
          <label className="inline-select">
            <span>Kind</span>
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="">All imports</option>
              <option value="billing">Billing</option>
              <option value="utilization">Utilization</option>
            </select>
          </label>
        }
      >
        {imports.loading && <Loading rows={4} />}
        {imports.error && <ErrorNote message={imports.error} onRetry={imports.refetch} />}
        {imports.data && imports.data.items.length === 0 && (
          <Empty title="No imports yet">
            Upload a billing and a utilization CSV above, or run{" "}
            <code>python scripts/seed_sample_data.py</code> to load the labelled sample.
          </Empty>
        )}
        {imports.data && imports.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Kind</th>
                  <th scope="col">File</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">
                    Rows
                  </th>
                  <th scope="col" className="num">
                    Accepted
                  </th>
                  <th scope="col" className="num">
                    Rejected
                  </th>
                  <th scope="col" className="num">
                    Warnings
                  </th>
                  <th scope="col">Period</th>
                  <th scope="col">Source</th>
                  <th scope="col">Imported</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {imports.data.items.map((item) => (
                  <tr key={item.id} className={item.id === selectedId ? "selected" : ""}>
                    <td className="num">{item.id}</td>
                    <td>{titleCase(item.kind)}</td>
                    <td className="mono">{item.filename}</td>
                    <td>
                      <Badge tone={statusTone(item.status)}>{titleCase(item.status)}</Badge>
                    </td>
                    <td className="num">{item.row_count}</td>
                    <td className="num">{item.accepted_row_count}</td>
                    <td className="num">{item.rejected_row_count}</td>
                    <td className="num">{item.warning_count}</td>
                    <td className="nowrap">
                      {item.period_start ? formatDate(item.period_start) : "—"}
                      {item.period_end && item.period_end !== item.period_start
                        ? ` – ${formatDate(item.period_end)}`
                        : ""}
                    </td>
                    <td>
                      <Badge tone={item.source === "sample" ? "warn" : "neutral"}>
                        {item.source}
                      </Badge>
                    </td>
                    <td className="nowrap">{formatDateTime(item.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-small btn-ghost"
                        onClick={() => setSelectedId(item.id)}
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {imports.data && (
          <p className="muted">
            Showing {imports.data.items.length} of {imports.data.total} import attempt(s).
          </p>
        )}
      </Card>

      {selectedId && (
        <Card
          title={`Import #${selectedId} detail`}
          subtitle="Validation result, content hash and row-level issues."
          actions={
            <button
              type="button"
              className="btn btn-small btn-ghost"
              onClick={() => setSelectedId(null)}
            >
              Close
            </button>
          }
        >
          {detail.loading && <Loading />}
          {detail.error && <ErrorNote message={detail.error} onRetry={detail.refetch} />}
          {detail.data && (
            <>
              <dl className="facts facts-inline">
                <div>
                  <dt>File</dt>
                  <dd className="mono">{detail.data.filename}</dd>
                </div>
                <div>
                  <dt>Kind</dt>
                  <dd>{titleCase(detail.data.kind)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>
                    <Badge tone={statusTone(detail.data.status)}>
                      {titleCase(detail.data.status)}
                    </Badge>
                  </dd>
                </div>
                <div>
                  <dt>Size</dt>
                  <dd>{detail.data.content_bytes.toLocaleString("en")} bytes</dd>
                </div>
                <div>
                  <dt>Issues</dt>
                  <dd>
                    {detail.data.issue_count} total · {detail.data.error_count} error(s)
                  </dd>
                </div>
                <div>
                  <dt>Currencies</dt>
                  <dd>{detail.data.currencies.join(", ") || "—"}</dd>
                </div>
                <div>
                  <dt>SHA-256</dt>
                  <dd className="mono tiny">{detail.data.content_sha256}</dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{formatDateTime(detail.data.created_at)}</dd>
                </div>
              </dl>
              {Object.keys(detail.data.stats).length > 0 && (
                <details className="raw-details">
                  <summary>Parser statistics</summary>
                  <pre>{JSON.stringify(detail.data.stats, null, 2)}</pre>
                </details>
              )}
            </>
          )}

          {issues.loading && <Loading rows={2} />}
          {issues.error && <ErrorNote message={issues.error} onRetry={issues.refetch} />}
          {issues.data && (
            <>
              <h3>Row-level issues</h3>
              <IssueTable issues={issues.data.items} />
              {issues.data.total > issues.data.items.length && (
                <p className="muted">
                  Showing {issues.data.items.length} of {issues.data.total} issue(s).
                </p>
              )}
            </>
          )}
          <Notes
            items={[
              "Parsing is local. CloudPilot never contacts a cloud provider and never requests credentials.",
              "Duplicate billing rows are stored for audit but excluded from analytic totals.",
              "Sample imports are labelled so screenshots cannot be mistaken for real spend.",
            ]}
          />
        </Card>
      )}
    </div>
  );
}
