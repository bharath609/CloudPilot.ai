import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDate } from "../lib";
import { Badge, Card, ErrorBox, Loading } from "../components/Card";
import type { AuditRow } from "../types";

const tone = (d: string) => (d === "accept" ? "ok" : d === "reject" ? "danger" : "warn");

export function AuditPage() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .audit()
      .then((d) => setRows(d.decisions))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="stack">
      <Card title="Audit Trail" subtitle="Append-only decision history">
        {error && <ErrorBox message={error} />}
        {!rows && !error && <Loading what="decisions" />}
        {rows && rows.length === 0 && <div className="empty">No decisions recorded yet.</div>}
        {rows && rows.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Finding</th>
                <th>Resource</th>
                <th>Decision</th>
                <th>Reviewer</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{formatDate(r.created_at)}</td>
                  <td className="mono">{r.finding_id}</td>
                  <td className="mono">{r.resource_id ?? "—"}</td>
                  <td><Badge tone={tone(r.decision)}>{r.decision}</Badge></td>
                  <td>{r.reviewer}</td>
                  <td className="muted">{r.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
