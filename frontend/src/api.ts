import type {
  AnomalyResult,
  AuditRow,
  Costs,
  Filters,
  Finding,
  Forecast,
  ImportRow,
  Investigation,
  PolicyResult,
  Resource,
  SimulationResult,
  Summary,
} from "./types";

const BASE = (import.meta as any).env?.VITE_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return (await res.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${path} -> ${res.status} ${text}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => get<{ status: string; version: string }>("/api/health"),
  filters: () => get<Filters>("/api/filters"),
  summary: (currency: string) => get<Summary>(`/api/summary?currency=${currency}`),
  costs: (currency: string, granularity: string) =>
    get<Costs>(`/api/costs?currency=${currency}&granularity=${granularity}`),
  resources: (currency?: string) =>
    get<{ resources: Resource[] }>(`/api/resources${currency ? `?currency=${currency}` : ""}`),
  findings: (currency?: string) =>
    get<{ findings: Finding[] }>(`/api/findings${currency ? `?currency=${currency}` : ""}`),
  decide: (findingId: string, decision: string, note: string, reviewer: string) =>
    post<{ ok: boolean }>(`/api/findings/${findingId}/decisions`, { decision, note, reviewer }),
  imports: () => get<{ imports: ImportRow[] }>("/api/imports"),
  audit: () => get<{ decisions: AuditRow[] }>("/api/audit"),
  forecasts: (currency: string) => get<Forecast>(`/api/forecasts?currency=${currency}`),
  simulate: (payload: {
    resource_id: string;
    scenario: string;
    utilization_retention?: number;
    sku_ratio?: number;
  }) => post<SimulationResult>("/api/v1/twin/simulate", payload),
  anomalySpending: (currency: string) =>
    post<AnomalyResult>("/api/v1/anomalies/spending", { currency }),
  anomalyCapacity: (resourceId: string) =>
    post<AnomalyResult>("/api/v1/anomalies/capacity", { resource_id: resourceId }),
  anomalyPerformance: (resourceId: string) =>
    post<AnomalyResult>("/api/v1/anomalies/performance", { resource_id: resourceId }),
  policy: (payload: {
    action_type: string;
    resource_id: string;
    environment: string;
    requesting_user: string;
    spending_delta: number;
  }) => post<PolicyResult>("/api/v1/policies/evaluate", payload),
  investigate: (findingId: string) =>
    post<Investigation>("/api/v1/investigation/start", { finding_id: findingId }),
  verify: (payload: {
    action_id: string;
    resource_id: string;
    expected: Record<string, unknown>;
    observed: Record<string, unknown>;
  }) => post<any>("/api/v1/verification/run", payload),
};
