import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDate, formatMoney } from "../lib";
import { Badge, Card, ErrorBox, Loading } from "../components/Card";
import type { DataStatus, ImportReport, ImportRow } from "../types";

type Dataset = "billing" | "resources";

const BILLING_COLUMNS = {
  required: "invoice_date, provider, service, amount, currency",
  optional:
    "project, region, environment, resource_id, resource_type, usage_amount, unit, unit_price, sku",
};

const RESOURCE_COLUMNS = {
  required: "resource_id",
  optional:
    "name, resource_type, provider, region, environment, currency, cost_per_hour, cpu_pct, memory_pct, status, sku",
};

function UploadCard({
  dataset,
  title,
  subtitle,
  columns,
  onDone,
}: {
  dataset: Dataset;
  title: string;
  subtitle: string;
  columns: { required: string; optional: string };
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"replace" | "append">("replace");
  const [currency, setCurrency] = useState<"USD" | "EUR" | "INR">("USD");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      setError("File is larger than 25 MB. Split it into smaller files.");
      return;
    }
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const content = await file.text();
      const payload =
        dataset === "billing"
          ? { filename: file.name, content, mode }
          : { filename: file.name, content, mode, currency };
      const result =
        dataset === "billing" ? await api.importBilling(payload) : await api.importResources(payload);
      setReport(result);
      if (result.ok) onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title={title}
      subtitle={subtitle}
      right={
        <a className="btn ghost" href={api.templateUrl(dataset)} download>
          Download template
        </a>
      }
    >
      <div className="import-form">
        <label className="field">
          <span>CSV file</span>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setReport(null);
              setError(null);
            }}
          />
        </label>
        <label className="field">
          <span>How to apply it</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as "replace" | "append")}>
            <option value="replace">Replace current dataset</option>
            <option value="append">Append to current dataset</option>
          </select>
        </label>
        {dataset === "resources" && (
          <label className="field">
            <span>Currency when the file has none</span>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value as "USD" | "EUR" | "INR")}
            >
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="INR">INR</option>
            </select>
          </label>
        )}
        <div className="field">
          <span>&nbsp;</span>
          <button className="btn primary" onClick={submit} disabled={busy || !file}>
            {busy ? "Importing…" : "Import"}
          </button>
        </div>
      </div>

      <div className="inline-note">
        <b>Required:</b> <span className="mono">{columns.required}</span>
        <br />
        <b>Optional:</b> <span className="mono">{columns.optional}</span>
        <br />
        Amounts must already be in their own currency (USD, EUR, INR). No FX conversion is applied.
        Dates use YYYY-MM-DD. Common export headers such as <span className="mono">usage_date</span>,{" "}
        <span className="mono">cost_amount</span>, <span className="mono">currency_code</span>, and{" "}
        <span className="mono">cpu_avg_pct</span> are recognised automatically.
        {dataset === "resources" &&
          " A utilization-only export is accepted; resources are collapsed to the latest snapshot per resource_id."}
      </div>

      {error && <ErrorBox message={error} />}

      {report && (
        <div className={report.ok ? "report ok" : "report bad"}>
          <div className="report-head">
            <Badge tone={report.ok ? "ok" : "danger"}>{report.ok ? "Imported" : "Not imported"}</Badge>
            <span className="muted">
              accepted {report.accepted} · rejected {report.rejected}
            </span>
          </div>
          <p>{report.message}</p>
          {Object.keys(report.currencies).length > 0 && (
            <div className="chip-row">
              {Object.entries(report.currencies).map(([currency, count]) => (
                <span className="chip" key={currency}>
                  {currency}: {count}
                </span>
              ))}
            </div>
          )}
          {report.warnings.map((warning, index) => (
            <div className="inline-warn" key={index}>
              {warning}
            </div>
          ))}
          {report.errors.length > 0 && (
            <>
              <div className="mini-title">Rejected rows</div>
              <ul className="list warn-list">
                {report.errors.slice(0, 20).map((issue, index) => (
                  <li key={index}>
                    line {issue.line}: {issue.message}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

const originTone = (origin: string) =>
  origin === "uploaded" ? "ok" : origin === "mixed" ? "warn" : "info";

export function ImportsPage() {
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [imports, setImports] = useState<ImportRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setError(null);
    Promise.all([api.dataStatus(), api.imports()])
      .then(([s, i]) => {
        setStatus(s);
        setImports(i.imports);
      })
      .catch((e) => setError(String(e)));
  };

  useEffect(load, []);

  const reset = async (mode: "demo" | "empty") => {
    const label =
      mode === "demo"
        ? "Replace the current data with the demo dataset?"
        : "Delete every billing row, resource, finding, and decision?";
    if (!window.confirm(label)) return;
    setBusy(true);
    try {
      await api.resetData(mode);
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <Card
        title="Your data"
        subtitle="What the app currently holds, and where it came from"
        right={
          status ? (
            <Badge tone={status.mode === "demo" ? "warn" : status.mode === "empty" ? "muted" : "ok"}>
              {status.mode === "demo"
                ? "Demo dataset"
                : status.mode === "imported"
                ? "Your data"
                : status.mode === "mixed"
                ? "Mixed data"
                : "No data"}
            </Badge>
          ) : undefined
        }
      >
        {error && <ErrorBox message={error} />}
        {!status && !error && <Loading what="dataset status" />}
        {status && (
          <>
            {status.currencies.length === 0 ? (
              <div className="empty">
                There are no billing rows. Import a CSV below, or restore the demo dataset.
              </div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Currency</th>
                    <th>Origin</th>
                    <th className="right">Rows</th>
                    <th>Window</th>
                    <th className="right">Total</th>
                    <th className="right">Resources</th>
                    <th className="right">Findings</th>
                  </tr>
                </thead>
                <tbody>
                  {status.currencies.map((row) => (
                    <tr key={row.currency}>
                      <td className="strong">{row.currency}</td>
                      <td>
                        <Badge tone={originTone(row.origin)}>{row.origin}</Badge>
                      </td>
                      <td className="right">{row.rows.toLocaleString()}</td>
                      <td className="mono">
                        {formatDate(row.start)} → {formatDate(row.end)}
                      </td>
                      <td className="right mono">{formatMoney(row.total, row.currency)}</td>
                      <td className="right">{row.resources}</td>
                      <td className="right">{row.findings}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="inline-note">
              Totals are per currency. The app never adds USD, EUR, and INR together.
              {status.last_import_at ? ` Last import: ${formatDate(status.last_import_at)}.` : ""}
            </div>
          </>
        )}
      </Card>

      <div className="import-grid">
        <UploadCard
          dataset="billing"
          title="Import billing CSV"
          subtitle="Your cost rows drive the Command Center, Cost Explorer, Forecasts, and spending anomalies"
          columns={BILLING_COLUMNS}
          onDone={load}
        />
        <UploadCard
          dataset="resources"
          title="Import resource inventory CSV"
          subtitle="Utilization snapshots drive the Resources page and threshold-based findings"
          columns={RESOURCE_COLUMNS}
          onDone={load}
        />
      </div>

      <Card title="Dataset controls" subtitle="Switch between your data and the built-in demo">
        <div className="button-row">
          <button className="btn" disabled={busy} onClick={() => reset("demo")}>
            Restore demo dataset
          </button>
          <button className="btn" disabled={busy} onClick={() => reset("empty")}>
            Delete all data
          </button>
        </div>
        <div className="inline-note">
          “Replace current dataset” on an import already removes the demo rows. Restore demo brings
          back the deterministic sample data.
        </div>
      </Card>

      <Card title="Import history" subtitle="Every accepted file, by currency">
        {!imports && !error && <Loading what="imports" />}
        {imports && imports.length === 0 && <div className="empty">No imports recorded yet.</div>}
        {imports && imports.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Dataset</th>
                <th>Source</th>
                <th>Currency</th>
                <th className="right">Rows</th>
                <th>Imported</th>
              </tr>
            </thead>
            <tbody>
              {imports.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.filename}</td>
                  <td>{row.dataset ?? "billing"}</td>
                  <td>
                    <Badge tone={row.source === "sample" ? "warn" : "ok"}>{row.source}</Badge>
                  </td>
                  <td>{row.currency}</td>
                  <td className="right">{row.row_count.toLocaleString()}</td>
                  <td>{formatDate(row.imported_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
