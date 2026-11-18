import { useMemo, useState } from "react";

import { api } from "../api/client";
import { useQuery } from "../api/hooks";
import { Badge, Card, Empty, ErrorNote, Field, Loading, Notes } from "../components/ui";
import { formatDate, formatDateTime, formatMoney, formatPercent } from "../lib/money";
import { useAppState } from "../state/AppState";

export function ResourcesPage() {
  const { currency, filters } = useAppState();
  const [provider, setProvider] = useState("");
  const [environment, setEnvironment] = useState("");
  const [search, setSearch] = useState("");

  const resources = useQuery(
    (signal) =>
      api.resources(
        {
          currency,
          provider: provider || undefined,
          environment: environment || undefined,
          limit: 200,
        },
        signal,
      ),
    [currency, provider, environment],
  );

  const visible = useMemo(() => {
    const items = resources.data?.items ?? [];
    const needle = search.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) =>
      [item.resource_id, item.owner, item.team, item.service, item.project]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [resources.data, search]);

  const idle = visible.filter((item) => item.idle_candidate).length;
  const rightsize = visible.filter((item) => item.rightsize_candidate).length;
  const shortWindow = visible.filter((item) => item.observation_days < 14).length;

  return (
    <div className="stack">
      <Card
        title="Observation scope"
        subtitle="Read-only inventory. Idle and rightsize flags are threshold pre-checks, not findings."
      >
        {filters && (
          <div className="filter-grid filter-grid-3">
            <Field label="Provider">
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                <option value="">All providers</option>
                {filters.providers.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Environment">
              <select
                value={environment}
                onChange={(event) => setEnvironment(event.target.value)}
              >
                <option value="">All environments</option>
                {filters.environments.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Search resource or owner">
              <input
                type="search"
                value={search}
                placeholder="i-demo-… or owner@example.test"
                onChange={(event) => setSearch(event.target.value)}
              />
            </Field>
          </div>
        )}
        {resources.data && (
          <p className="muted">
            Window {formatDate(resources.data.window.start)} –{" "}
            {formatDate(resources.data.window.end)} ({resources.data.window.days} days) ·{" "}
            {resources.data.items.length} of {resources.data.total} resource(s) on this page
          </p>
        )}
      </Card>

      <section className="stat-grid">
        <div className="stat stat-warn">
          <span className="stat-label">Idle pre-checks</span>
          <span className="stat-value">{idle}</span>
          <span className="stat-hint">CPU p95 max below threshold and memory p95 max below threshold</span>
        </div>
        <div className="stat">
          <span className="stat-label">Rightsize pre-checks</span>
          <span className="stat-value">{rightsize}</span>
          <span className="stat-hint">Mean CPU and memory below the rightsize thresholds</span>
        </div>
        <div className="stat">
          <span className="stat-label">Short observation windows</span>
          <span className="stat-value">{shortWindow}</span>
          <span className="stat-hint">Resources below 14 observation days</span>
        </div>
        <div className="stat">
          <span className="stat-label">Missing owners</span>
          <span className="stat-value">
            {visible.filter((item) => !item.owner || item.owner === "unassigned").length}
          </span>
          <span className="stat-hint">Assign an owner before any action is considered</span>
        </div>
      </section>

      <Card
        title="Resources with utilization samples"
        subtitle="Only resources that appear in both billing and utilization are listed."
      >
        {resources.loading && <Loading rows={5} />}
        {resources.error && <ErrorNote message={resources.error} onRetry={resources.refetch} />}
        {resources.data && visible.length === 0 && (
          <Empty title="No resources match">
            Import utilization samples or clear the filters.
          </Empty>
        )}
        {visible.length > 0 && (
          <div className="table-wrap">
            <table className="table-resources">
              <thead>
                <tr>
                  <th scope="col">Resource</th>
                  <th scope="col">Owner / team</th>
                  <th scope="col" className="num">
                    CPU avg
                  </th>
                  <th scope="col" className="num">
                    CPU p95 max
                  </th>
                  <th scope="col" className="num">
                    Mem avg
                  </th>
                  <th scope="col" className="num">
                    Mem p95 max
                  </th>
                  <th scope="col">Observation</th>
                  <th scope="col" className="num">
                    Window cost
                  </th>
                  <th scope="col">Flags</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.resource_id}>
                    <td>
                      <span className="mono">{item.resource_id}</span>
                      <span className="muted block">
                        {item.service} · {item.region} · {item.environment} · {item.project}
                      </span>
                      {item.observation_start && (
                        <span className="muted block tiny" title={formatDateTime(item.observation_end)}>
                          samples from {formatDateTime(item.observation_start)}
                        </span>
                      )}
                    </td>
                    <td>
                      <span>{item.owner ?? "unassigned"}</span>
                      <span className="muted block">{item.team ?? "untagged"}</span>
                    </td>
                    <td className="num">{formatPercent(item.cpu_avg_pct, 1)}</td>
                    <td className="num">{formatPercent(item.cpu_p95_max_pct, 1)}</td>
                    <td className="num">{formatPercent(item.memory_avg_pct, 1)}</td>
                    <td className="num">{formatPercent(item.memory_p95_max_pct, 1)}</td>
                    <td>
                      <span>{item.observation_days} day(s)</span>
                      <span className="muted block">{item.sample_count} samples</span>
                    </td>
                    <td className="num">
                      {item.window_cost
                        ? formatMoney(item.window_cost, item.currency)
                        : "unknown"}
                    </td>
                    <td>
                      <div className="flag-stack">
                        {item.idle_candidate && <Badge tone="warn">Idle candidate</Badge>}
                        {item.rightsize_candidate && (
                          <Badge tone="accent">Rightsize candidate</Badge>
                        )}
                        {!item.idle_candidate && !item.rightsize_candidate && (
                          <Badge tone="neutral">Observed</Badge>
                        )}
                      </div>
                      {item.warnings.length > 0 && (
                        <details className="inline-details">
                          <summary>{item.warnings.length} warning(s)</summary>
                          <ul>
                            {item.warnings.map((warning) => (
                              <li key={warning}>{warning}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {resources.data && (
          <>
            <div className="thresholds">
              <span>Idle: CPU p95 max &lt; {resources.data.thresholds.idle_cpu_p95_pct}% and memory p95 max &lt; {resources.data.thresholds.idle_memory_p95_pct}%</span>
              <span>Rightsize: mean CPU &lt; {resources.data.thresholds.rightsize_cpu_avg_pct}% and mean memory &lt; {resources.data.thresholds.rightsize_memory_avg_pct}%</span>
              <span>Eligibility: at least {resources.data.thresholds.min_observation_days} observation days and {resources.data.thresholds.min_samples} samples</span>
            </div>
            <Notes items={resources.data.notes} />
          </>
        )}
      </Card>
    </div>
  );
}
