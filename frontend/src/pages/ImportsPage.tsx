import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDate } from "../lib";
import { Card, ErrorBox, Loading } from "../components/Card";
import type { ImportRow } from "../types";

export function ImportsPage() {
  const [imports, setImports] = useState<ImportRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .imports()
      .then((d) => setImports(d.imports))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="stack">
      <Card title="Imports" subtitle="Synthetic billing imports by currency">
        {error && <ErrorBox message={error} />}
        {!imports && !error && <Loading what="imports" />}
        {imports && (
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Source</th>
                <th>Currency</th>
                <th className="right">Rows</th>
                <th>Imported</th>
              </tr>
            </thead>
            <tbody>
              {imports.map((i) => (
                <tr key={i.id}>
                  <td className="mono">{i.filename}</td>
                  <td>{i.source}</td>
                  <td>{i.currency}</td>
                  <td className="right">{i.row_count.toLocaleString()}</td>
                  <td>{formatDate(i.imported_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
